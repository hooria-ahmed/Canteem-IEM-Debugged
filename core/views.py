import bcrypt
import json
import csv
import io
from functools import wraps
from uuid import uuid4
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.views.generic import ListView
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db.models import Sum, Q, F, Count
from decimal import Decimal
from datetime import datetime, timedelta
from .models import (
    Dish, DishCategory, SalesTransaction, SaleItem, User,
    DailyReport, Expense, RawMaterial, ExpenseCategory,
    StockAdjustment, AuditLog, RawMaterialCategory, MealSession,
    Supplier, PurchaseOrder, PurchaseOrderItem
)
from django.db import transaction, models
from django.contrib import messages


MONEY_QUANTUM = Decimal('0.01')


def _money(value):
    """Normalize monetary values to the precision stored by the database."""
    return Decimal(value).quantize(MONEY_QUANTUM)


def _invalidate_manager_cache(target_date=None):
    """Invalidate dashboard data after a sale/stock/finance mutation."""
    from django.core.cache import cache
    target_date = target_date or timezone.localdate()
    cache.delete(f"manager_dashboard_data_{target_date.strftime('%Y%m%d')}")

# --- CART HELPER ---
def _build_cart_context(cart):
    """Rebuild cart_items list and grand_total from the session cart dict."""
    cart_items = []
    grand_total = Decimal('0.00')
    if not cart:
        return cart_items, grand_total

    # Batch fetch dishes to avoid N+1 queries
    dish_ids = [int(sid) for sid in cart.keys()]
    dishes = Dish.objects.filter(id__in=dish_ids).in_bulk()

    for dish_id_str, item_data in cart.items():
        dish = dishes.get(int(dish_id_str))
        if dish:
            qty = item_data['qty']
            price = _money(dish.selling_price)
            line_total = _money(price * qty)
            cart_items.append({
                'dish_id': dish_id_str,
                'name': dish.name,
                'price': price,
                'qty': qty,
                'total': line_total,
            })
            grand_total += line_total
            
    return cart_items, _money(grand_total)

# --- ACCESS CONTROL DECORATORS ---
def manager_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if 'user_id' not in request.session:
            return redirect('/login/')
        if request.session.get('user_role') not in {'manager', 'admin'}:
            return redirect('/400/') # Or a forbidden page
        return view_func(request, *args, **kwargs)
    return wrapper

def cashier_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if 'user_id' not in request.session:
            return redirect('/login/')
        if request.session.get('user_role') not in {'cashier', 'manager', 'admin'}:
            return redirect('/400/')
        return view_func(request, *args, **kwargs)
    return wrapper

def kitchen_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if 'user_id' not in request.session:
            return redirect('/login/')
        if request.session.get('user_role') not in {'kitchen', 'cashier', 'manager', 'admin'}:
            return redirect('/400/')
        return view_func(request, *args, **kwargs)
    return wrapper

# --- AUDIT LOGGER ---
def log_audit(request, action_code, entity_type, entity_id, old_val=None, new_val=None):
    try:
        AuditLog.objects.create(
            user_id=request.session.get('user_id'),
            action_code=action_code,
            entity_type=entity_type,
            entity_id=entity_id,
            old_values=old_val,
            new_values=new_val,
            ip_address=request.META.get('REMOTE_ADDR')
        )
    except Exception:
        pass

# --- AUTHENTICATION VIEWS ---
def login_view(request):
    if 'user_id' in request.session:
        role = request.session.get('user_role')
        if role in {'manager', 'admin'}:
            return redirect('/manager/')
        elif role == 'kitchen':
            return redirect('/kitchen/')
        return redirect('/pos/')

    if request.method == 'POST':
        username = request.POST.get('username')
        password_str = request.POST.get('password', '')
        password = password_str.encode('utf-8') if password_str else b''

        try:
            user = User.objects.get(user_name=username, is_active=True)
            if user.password_hash and bcrypt.checkpw(password, user.password_hash.encode('utf-8')):
                request.session.cycle_key()
                request.session['user_id'] = user.id
                request.session['user_name'] = user.full_name
                request.session['user_role'] = user.role
                request.session['user_avatar'] = user.avatar_path
                user.last_login_at = timezone.now()
                user.save(update_fields=['last_login_at', 'updated_at'])
                log_audit(request, 'USER_LOGIN', 'User', user.id)
                if user.role in {'manager', 'admin'}:
                    return redirect('/manager/')
                elif user.role == 'kitchen':
                    return redirect('/kitchen/')
                else:
                    return redirect('/pos/')
            else:
                return render(request, 'login.html', {'error': 'Invalid username or password'})
        except (User.DoesNotExist, ValueError):
            return render(request, 'login.html', {'error': 'Invalid username or password'})

    return render(request, 'login.html')

def logout_view(request):
    if 'user_id' in request.session:
        log_audit(request, 'USER_LOGOUT', 'User', request.session.get('user_id'))
    request.session.flush()
    return redirect('/login/')

# --- POS & CART VIEWS ---
@method_decorator(cashier_required, name='dispatch')
class CashierView(ListView):
    model = Dish
    template_name = 'pos.html'
    context_object_name = 'dishes'

    def dispatch(self, request, *args, **kwargs):
        if 'user_id' not in request.session:
            return redirect('/login/')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return Dish.objects.filter(is_available=True).prefetch_related(
            'ingredients',
            'ingredients__raw_material'
        ).order_by('category')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = DishCategory.objects.filter(is_active=True)
        cart = self.request.session.get('cart', {})
        cart_items = []
        grand_total = Decimal('0.00')
        for dish_id, item_data in cart.items():
            try:
                dish = Dish.objects.get(id=dish_id)
                quantity = item_data['qty']
                line_total = dish.selling_price * quantity
                cart_items.append({'dish_id': dish_id, 'name': dish.name, 'price': dish.selling_price, 'qty': quantity, 'total': line_total})
                grand_total += line_total
            except Dish.DoesNotExist:
                continue
        context['cart_items'] = cart_items
        context['grand_total'] = grand_total
        context['cashier_name'] = self.request.session.get('user_name', 'Unknown')
        last_txn_id = self.request.session.get('last_transaction_id')
        last_txn, last_txn_items = None, []
        if last_txn_id:
            try:
                last_txn = SalesTransaction.objects.get(id=last_txn_id)
                last_txn_items = last_txn.items.all()
                del self.request.session['last_transaction_id']
            except SalesTransaction.DoesNotExist:
                pass
        context['last_txn'] = last_txn
        context['last_txn_items'] = last_txn_items
        return context

@cashier_required
@require_POST
def add_to_cart(request, dish_id):
    try:
        dish = Dish.objects.get(id=dish_id)
    except Dish.DoesNotExist:
        return redirect('/pos/')
        
    cart = request.session.get('cart', {})
    dish_id_str = str(dish_id)
    current_qty = cart.get(dish_id_str, {}).get('qty', 0)
    
    if current_qty + 1 <= dish.stock:
        if dish_id_str in cart:
            cart[dish_id_str]['qty'] += 1
        else:
            cart[dish_id_str] = {'qty': 1}
        request.session['cart'] = cart
        
    return redirect('/pos/')

@cashier_required
@require_POST
def remove_from_cart(request, dish_id):
    cart = request.session.get('cart', {})
    dish_id_str = str(dish_id)
    if dish_id_str in cart:
        del cart[dish_id_str]
        request.session['cart'] = cart
    return redirect('/pos/')

# --- AJAX CART ENDPOINTS ---
@cashier_required
@require_POST
def add_to_cart_ajax(request, dish_id):

    try:
        dish = Dish.objects.prefetch_related('ingredients', 'ingredients__raw_material').get(id=dish_id)
    except Dish.DoesNotExist:
        return JsonResponse({'error': 'Dish not found'}, status=404)

    cart = request.session.get('cart', {})
    dish_id_str = str(dish_id)
    current_qty = cart.get(dish_id_str, {}).get('qty', 0)

    if current_qty + 1 > dish.stock:
        cart_items, grand_total = _build_cart_context(cart)
        response = render(request, 'cart_partial.html', {
            'cart_items': cart_items,
            'grand_total': grand_total,
        })
        response['HX-Trigger'] = json.dumps({"showStockError": f"Only {dish.stock} servings available for {dish.name}."})
        return response

    if dish_id_str in cart:
        cart[dish_id_str]['qty'] += 1
    else:
        cart[dish_id_str] = {'qty': 1}

    request.session['cart'] = cart
    request.session.modified = True
    cart_items, grand_total = _build_cart_context(cart)
    return render(request, 'cart_partial.html', {'cart_items': cart_items, 'grand_total': grand_total})

@cashier_required
@require_POST
def remove_from_cart_ajax(request, dish_id):
    """Decrement item qty by 1; remove from cart if qty reaches 0."""
    cart = request.session.get('cart', {})
    dish_id_str = str(dish_id)
    if dish_id_str in cart:
        cart[dish_id_str]['qty'] -= 1
        if cart[dish_id_str]['qty'] <= 0:
            del cart[dish_id_str]
    request.session['cart'] = cart
    request.session.modified = True
    cart_items, grand_total = _build_cart_context(cart)
    return render(request, 'cart_partial.html', {'cart_items': cart_items, 'grand_total': grand_total})

@cashier_required
@require_POST
def clear_cart_ajax(request):
    request.session['cart'] = {}
    request.session.modified = True
    cart_items, grand_total = _build_cart_context({})
    return render(request, 'cart_partial.html', {'cart_items': cart_items, 'grand_total': grand_total})

# --- CUSTOM ERROR PAGES ---
def custom_400(request, exception=None):
    return render(request, '400.html', status=400)

def custom_404(request, exception=None):
    return render(request, '404.html', status=404)

def custom_500(request, exception=None):
    return render(request, '500.html', status=500)

# --- CASH TENDERING SCREEN ---
@cashier_required
def checkout_screen_view(request):
    cart = request.session.get('cart', {})
    if not cart:
        return redirect('/pos/')
    cart_items, grand_total = _build_cart_context(cart)
    return render(request, 'checkout.html', {'cart_items': cart_items, 'grand_total': grand_total})

# --- PROCESS CHECKOUT ---
@cashier_required
@require_POST
def process_checkout(request):
    cart = request.session.get('cart', {})
    if not cart:
        return redirect('/pos/')
    try:
        logged_in_user_id = request.session.get('user_id')
        cashier = User.objects.get(id=logged_in_user_id)
        amount_received_str = request.POST.get('amount_received', '0')
        if not amount_received_str:
            amount_received_str = '0'
        amount_received = _money(amount_received_str)
        payment_method = request.POST.get('payment_method', 'cash')
        order_type = request.POST.get('order_type', 'dine_in')
        table_no = request.POST.get('table_no', '')

        valid_payment_methods = {choice[0] for choice in SalesTransaction._meta.get_field('payment_method').choices}
        valid_order_types = {choice[0] for choice in SalesTransaction._meta.get_field('order_type').choices}
        if payment_method not in valid_payment_methods:
            raise ValueError('Invalid payment method')
        if order_type not in valid_order_types:
            raise ValueError('Invalid order type')
        
        grand_total = Decimal('0.00')
        for dish_id, item_data in cart.items():
            dish = Dish.objects.get(id=dish_id)
            price = _money(dish.selling_price)
            grand_total += price * item_data['qty']
        grand_total = _money(grand_total)
        
        # If card payment, amount received equals grand total implicitly, else calculate
        if payment_method in {'card', 'digital_wallet'}:
            amount_received = grand_total
        elif payment_method == 'credit':
            amount_received = Decimal('0.00')

        if payment_method == 'cash' and amount_received < grand_total:
            raise ValueError('Amount received is less than the order total')

        change_returned = _money(max(amount_received - grand_total, Decimal('0.00')))
        
        # FIXED: Get meal session dynamically based on current time
        now = timezone.localtime()
        current_time = now.time()
        meal_session = MealSession.objects.filter(
            start_time__lte=current_time,
            end_time__gte=current_time,
            is_active=True
        ).first()
        
        # Handle cross-midnight sessions (e.g. 10 PM to 2 AM)
        if not meal_session:
            meal_session = MealSession.objects.filter(
                is_active=True,
                start_time__gt=F('end_time')
            ).filter(
                Q(start_time__lte=current_time) | Q(end_time__gte=current_time)
            ).first()
        
        # Fallback if no session matches current time
        if not meal_session:
            meal_session = MealSession.objects.first()
        
        if not meal_session:
            raise ValueError("No meal sessions configured in system")
        
        with transaction.atomic():
            # Create transaction record first
            txn = SalesTransaction.objects.create(
                transaction_no=f"WEB-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6].upper()}",
                cashier=cashier,
                meal_session=meal_session,
                sale_date=now.date(),
                sale_time=now.time(),
                sub_total=grand_total,
                total_amount=grand_total,
                amount_received=amount_received,
                change_returned=change_returned,
                payment_method=payment_method,
                order_type=order_type,
                table_no=table_no,
                status='completed'
            )
            
            for dish_id, item_data in cart.items():
                dish = Dish.objects.get(id=dish_id)
                qty = item_data['qty']
                dish_cost_per_portion = Decimal('0.00')
                
                # 1. Calculate cost
                for ingredient_link in dish.ingredients.all():
                    rm = ingredient_link.raw_material
                    item_cost = rm.cost_per_unit * ingredient_link.quantity_required
                    dish_cost_per_portion += item_cost
                    
                # 2. Lock and deduct stock safely
                for ingredient_link in dish.ingredients.all():
                    # select_for_update() locks the row until the transaction completes, preventing race conditions
                    rm = RawMaterial.objects.select_for_update().get(id=ingredient_link.raw_material.id)
                    qty_to_subtract = ingredient_link.quantity_required * qty
                    
                    if rm.current_stock < qty_to_subtract:
                        raise ValueError(f"Insufficient stock for {rm.name}. Needed {qty_to_subtract}, but only {rm.current_stock} available.")
                    
                    q_before = rm.current_stock
                    rm.current_stock -= qty_to_subtract
                    rm.save(update_fields=['current_stock', 'updated_at'])
                    q_after = rm.current_stock
                    
                    # Log the stock deduction
                    StockAdjustment.objects.create(
                        raw_material=rm,
                        adjusted_by=cashier,
                        adjusted_type='deduction',
                        quantity_before=q_before,
                        adjusted_qty=qty_to_subtract,
                        quantity_after=q_after,
                        reason=f"Sale: {txn.transaction_no} ({dish.name} x {qty})",
                        reference_doc=txn.transaction_no
                    )
                    
                # 3. Snapshot Price and Create Sale Item
                SaleItem.objects.create(
                    transaction=txn,
                    dish=dish,
                    dish_name=dish.name,
                    quantity=qty,
                    unit_price=_money(dish.selling_price),
                    unit_cost=dish_cost_per_portion,
                    line_total=_money(dish.selling_price * qty)
                )

                Dish.objects.filter(pk=dish.pk).update(total_sold=F('total_sold') + qty)
            
            log_audit(request, 'TXN_COMPLETED', 'SalesTransaction', txn.id, new_val={'total': float(grand_total)})
            request.session['last_transaction_id'] = txn.id
            request.session['cart'] = {}
            
            # Clear manager dashboard cache for today
            _invalidate_manager_cache(now.date())
            
            if request.headers.get('HX-Request'):
                items = txn.items.all()
                return render(request, 'receipt_partial.html', {'txn': txn, 'items': items})
            
            return redirect('receipt', txn_id=txn.id)
    except ValueError as e:
        if request.headers.get('HX-Request'):
            return HttpResponse(f"Checkout failed: {str(e)}", status=400)
    except Exception:
        if request.headers.get('HX-Request'):
            return HttpResponse("Checkout failed because of an internal error.", status=500)
    return redirect('/pos/')

# --- RECEIPT VIEW ---
@cashier_required
def receipt_view(request, txn_id):
    txn = get_object_or_404(SalesTransaction, id=txn_id)
    items = SaleItem.objects.filter(transaction=txn)
    return render(request, 'receipt.html', {'txn': txn, 'items': items})


# --- MANAGER DASHBOARD VIEW ---
@manager_required
def manager_dashboard(request):
    today = timezone.localdate()
    
    # 2 Hours Cache check
    from django.core.cache import cache
    cache_key = f"manager_dashboard_data_{today.strftime('%Y%m%d')}"
    cached_context = cache.get(cache_key)
    if cached_context:
        cached_context['manager_name'] = request.session.get('user_name', 'Manager')
        return render(request, 'manager.html', cached_context)

    daily_sales = SalesTransaction.objects.filter(sale_date=today, status='completed')
    total_revenue = daily_sales.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
    
    # New metrics for dark dashboard
    orders_today = daily_sales.count()
    active_menu_items = Dish.objects.filter(is_available=True).count()
    
    sales_items_today = SaleItem.objects.filter(transaction__sale_date=today, transaction__status='completed')
    
    # Optimized COGS calculation
    total_cogs = sales_items_today.aggregate(
        total=Sum(F('unit_cost') * F('quantity'), output_field=models.DecimalField())
    )['total'] or Decimal('0.00')
    
    gross_profit = total_revenue - total_cogs
    daily_expenses = Expense.objects.filter(expense_date=today)
    total_expenses = daily_expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    net_profit = gross_profit - total_expenses
    
    # Sales trend: prefer 24h hourly data; fall back to 7-day daily history
    # when today has no/very little data so the chart is never blank.
    trend_labels = []
    trend_data = []
    now_dt = timezone.localtime().replace(tzinfo=None)
    cutoff = now_dt - timedelta(hours=23)

    recent_sales = SalesTransaction.objects.filter(
        sale_date__gte=cutoff.date(),
        status='completed'
    ).only('sale_date', 'sale_time', 'total_amount')

    for i in range(23, -1, -1):
        hr_time = (now_dt - timedelta(hours=i))
        hr_start = hr_time.replace(minute=0, second=0, microsecond=0)
        hr_end   = hr_time.replace(minute=59, second=59, microsecond=999999)
        hr_total = sum(
            txn.total_amount for txn in recent_sales
            if txn.sale_date == hr_time.date() and hr_start.time() <= txn.sale_time <= hr_end.time()
        )
        trend_labels.append(hr_start.strftime("%H:%M"))
        trend_data.append(float(hr_total))

    # If the 24h window is entirely empty, fall back to 7-day daily totals
    # so the dashboard always shows meaningful historical context.
    if sum(trend_data) == 0:
        seven_days_ago = today - timedelta(days=6)
        daily_qs = (
            SalesTransaction.objects
            .filter(sale_date__range=(seven_days_ago, today), status='completed')
            .values('sale_date')
            .annotate(day_total=Sum('total_amount'))
            .order_by('sale_date')
        )
        rev_map = {row['sale_date']: float(row['day_total']) for row in daily_qs}
        trend_labels = []
        trend_data   = []
        for offset in range(6, -1, -1):
            d = today - timedelta(days=offset)
            trend_labels.append(d.strftime('%b %d'))
            trend_data.append(rev_map.get(d, 0))

    # Active orders for live monitor (ONLY pending and preparing)
    active_orders = SalesTransaction.objects.filter(
        sale_date=today,
        kitchen_status__in=['pending', 'preparing']
    ).order_by('-sale_time')[:10]

    # Sales by category
    category_revenue = sales_items_today.values('dish__category__name').annotate(cat_total=Sum('line_total')).order_by('-cat_total')
    sales_by_category = []
    colors = ['#10b981', '#f59e0b', '#3b82f6', '#ef4444']
    for i, cat in enumerate(category_revenue):
        sales_by_category.append({
            'name': cat['dish__category__name'] or 'Uncategorized',
            'amount': cat['cat_total'],
            'percent': (cat['cat_total'] / total_revenue * 100) if total_revenue > 0 else 0,
            'color': colors[i % len(colors)]
        })

    # Top selling items
    top_selling = sales_items_today.values(
        'dish_name',
        category_name=F('dish__category__name')
    ).annotate(
        revenue=Sum('line_total'),
        qty_sold=Sum('quantity')
    ).order_by('-qty_sold')[:3]

    for item in top_selling:
        item['category'] = item['category_name']

    # Critical stock alerts: items below their reorder_level OR items
    # with reorder_level=0 that have been fully depleted (stock == 0).
    low_stock_items = RawMaterial.objects.filter(
        Q(reorder_level__gt=0, current_stock__lte=F('reorder_level')) |
        Q(reorder_level=0, current_stock=0),
        is_active=True
    )
    profit_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else Decimal('0.00')
    low_stock_count = low_stock_items.count()
    
    context = {
        'date': today,
        'total_revenue': total_revenue,
        'total_cogs': total_cogs,
        'gross_profit': gross_profit,
        'total_expenses': total_expenses,
        'net_profit': net_profit,
        'orders_today': orders_today,
        'active_menu_items': active_menu_items,
        'active_orders': list(active_orders),
        'sales_by_category': sales_by_category,
        'top_selling': list(top_selling),
        'low_stock_items': list(low_stock_items),
        'low_stock_count': low_stock_count,
        'profit_margin': profit_margin,
        'trend_labels': json.dumps(trend_labels),
        'trend_data': json.dumps(trend_data),
        'manager_name': request.session.get('user_name', 'Manager')
    }
    cache.set(cache_key, context, 7200)  # Cache for 2 hours
    return render(request, 'manager.html', context)

# --- DAILY REPORT VIEW ---
@manager_required
def generate_daily_report(request, report_date=None):
    try:
        if report_date:
            target_date = datetime.strptime(report_date, "%Y-%m-%d").date()
        else:
            target_date = timezone.localdate()
    except ValueError:
        target_date = timezone.localdate()
    daily_transactions = SalesTransaction.objects.filter(sale_date=target_date, status='completed')
    gross_revenue = daily_transactions.aggregate(Sum('sub_total'))['sub_total__sum'] or Decimal('0.00')
    total_discounts = daily_transactions.aggregate(Sum('discount_amount'))['discount_amount__sum'] or Decimal('0.00')
    net_revenue = daily_transactions.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
    total_transactions_count = daily_transactions.count()
    sales_items = SaleItem.objects.filter(transaction__sale_date=target_date, transaction__status='completed')
    cost_of_goods_sold = Decimal('0.00')
    total_items_sold = 0
    for item in sales_items:
        cost = item.unit_cost if item.unit_cost else Decimal('0.00')
        cost_of_goods_sold += (cost * item.quantity)
        total_items_sold += item.quantity
    gross_profit = net_revenue - cost_of_goods_sold
    daily_expenses = Expense.objects.filter(expense_date=target_date)
    total_expenses = daily_expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    net_profit = gross_profit - total_expenses
    revenue_by_session = {
        row['meal_session__name']: row['revenue'] or Decimal('0.00')
        for row in daily_transactions.values('meal_session__name').annotate(revenue=Sum('total_amount'))
    }
    new_report, created = DailyReport.objects.update_or_create(
        report_date=target_date,
        defaults={
            'generated_by_id': request.session.get('user_id'),
            'total_transactions': total_transactions_count,
            'total_items_sold': total_items_sold,
            'gross_revenue': gross_revenue,
            'total_discounts': total_discounts,
            'net_revenue': net_revenue,
            'cost_of_goods_sold': cost_of_goods_sold,
            'gross_profit': gross_profit,
            'total_expenses': total_expenses,
            'net_profit': net_profit,
            'breakfast_revenue': revenue_by_session.get('breakfast', Decimal('0.00')),
            'lunch_revenue': revenue_by_session.get('lunch', Decimal('0.00')),
            'snack_revenue': revenue_by_session.get('snack', Decimal('0.00')),
        },
    )
    return render(request, 'report.html', {'report': new_report})

# --- EXPENSE ENTRY VIEW ---
@manager_required
def add_expense_view(request):
    if 'user_id' not in request.session:
        return redirect('/login/')
    if request.method == 'POST':
        title = request.POST.get('title')
        amount = request.POST.get('amount')
        expense_date = request.POST.get('expense_date')
        category_id = request.POST.get('category')
        try:
            amount = Decimal(amount)
            if amount <= 0:
                raise ValueError('Expense amount must be greater than zero')
            if not title or not title.strip():
                raise ValueError('Expense title is required')
            if not expense_date:
                raise ValueError('Expense date is required')
            user = User.objects.get(id=request.session.get('user_id'))
            category = ExpenseCategory.objects.get(id=category_id)
            exp = Expense.objects.create(category=category, recorded_by=user, title=title, amount=amount, expense_date=expense_date, payment_method='cash')
            log_audit(request, 'EXPENSE_ADDED', 'Expense', exp.id, new_val={'title': title, 'amount': float(amount)})
            
            # Clear manager dashboard cache for today
            _invalidate_manager_cache()
            
            return redirect('/manager/')
        except Exception as e:
            return render(request, 'add_expense.html', {
                'categories': ExpenseCategory.objects.filter(is_active=True),
                'error': str(e),
            })
    categories = ExpenseCategory.objects.all()
    return render(request, 'add_expense.html', {'categories': categories})

# --- RECIPE COSTING MATRIX (FIXED) ---
@manager_required
def recipe_costing_matrix(request):
    if 'user_id' not in request.session:
        return redirect('/login/')

    category_filter = request.GET.get('category', '')
    status_filter = request.GET.get('status', '')
    search_filter = request.GET.get('search', '')
    sort_param = request.GET.get('sort', 'name')

    dishes = Dish.objects.filter(is_available=True, selling_price__gt=0).prefetch_related('ingredients__raw_material').select_related('category')

    if category_filter:
        dishes = dishes.filter(category_id=category_filter)
    if search_filter:
        dishes = dishes.filter(name__icontains=search_filter)

    matrix_data = []
    total_cost = Decimal('0.00')
    total_revenue = Decimal('0.00')
    total_profit = Decimal('0.00')

    for dish in dishes:
        dish_cost = Decimal('0.00')
        has_ingredients = False
        for ingredient in dish.ingredients.all():
            has_ingredients = True
            dish_cost += (ingredient.raw_material.cost_per_unit * ingredient.quantity_required)

        selling_price = dish.selling_price
        profit = selling_price - dish_cost
        margin_percent = (profit / selling_price * 100) if selling_price > 0 else Decimal('0.00')

        if has_ingredients:
            if margin_percent >= 60:
                status_color, status_text = "#22c55e", "High Profit"
            elif margin_percent >= 30:
                status_color, status_text = "#f59e0b", "Average Profit"
            elif margin_percent > 0:
                status_color, status_text = "#ffc107", "Low Profit"
            else:
                status_color, status_text = "#ef4444", "Loss"
        else:
            status_color, status_text = "#9e9e9e", "No Recipe"

        matrix_data.append({
            'dish': dish.name,
            'category': dish.category.name if dish.category else 'Uncategorized',
            'cost_price': dish_cost,
            'selling_price': selling_price,
            'profit': profit,
            'margin': margin_percent,
            'color': status_color,
            'status': status_text,
            'is_no_recipe': not has_ingredients,
        })
        total_cost += dish_cost
        total_revenue += selling_price
        total_profit += profit

    # Status filter (applied after calculation since status is computed)
    if status_filter == 'profit':
        matrix_data = [r for r in matrix_data if r['profit'] > 0 and not r['is_no_recipe']]
    elif status_filter == 'loss':
        matrix_data = [r for r in matrix_data if r['profit'] <= 0 and not r['is_no_recipe']]
    elif status_filter == 'norecipe':
        matrix_data = [r for r in matrix_data if r['is_no_recipe']]

    # Sort
    sort_key = sort_param.lstrip('-')
    reverse = sort_param.startswith('-')
    if sort_key in ('name', 'cost', 'price', 'profit', 'margin'):
        key_map = {'name': 'dish', 'cost': 'cost_price', 'price': 'selling_price', 'profit': 'profit', 'margin': 'margin'}
        matrix_data.sort(key=lambda x: x[key_map[sort_key]], reverse=reverse)

    filtered_cost = sum(r['cost_price'] for r in matrix_data)
    filtered_profit = sum(r['profit'] for r in matrix_data)

    # Sort arrows for template
    def arrow(field):
        if sort_param == field:
            return '&#9650;'
        elif sort_param == '-' + field:
            return '&#9660;'
        return ''

    categories = DishCategory.objects.filter(is_active=True).order_by('name')

    context = {
        'matrix_data': matrix_data,
        'total_dishes': len(matrix_data),
        'total_cost': total_cost,
        'total_revenue': total_revenue,
        'total_profit': total_profit,
        'filtered_cost': filtered_cost,
        'filtered_profit': filtered_profit,
        'categories': categories,
        'category_filter': category_filter,
        'status_filter': status_filter,
        'search_filter': search_filter,
        'sort_arrow_name': arrow('name'),
        'sort_arrow_cost': arrow('cost'),
        'sort_arrow_price': arrow('price'),
        'sort_arrow_profit': arrow('profit'),
        'sort_arrow_margin': arrow('margin'),
        'manager_name': request.session.get('user_name', 'Manager'),
    }
    return render(request, 'costing.html', context)

# --- INVENTORY MANAGEMENT ---
@manager_required
def inventory_management(request):
    if 'user_id' not in request.session:
        return redirect('/login/')
    message, message_type = None, None
    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'add_stock':
            try:
                material_id = request.POST.get('material_id')
                qty = Decimal(request.POST.get('quantity', '0') or '0')
                if not material_id: message, message_type = "Please select a material.", "error"
                else:
                    if qty <= 0:
                        raise ValueError("Quantity must be > 0.")
                    with transaction.atomic():
                        rm = RawMaterial.objects.select_for_update().get(id=material_id)
                        before = rm.current_stock
                        rm.current_stock += qty
                        rm.save()
                        StockAdjustment.objects.create(raw_material=rm, adjusted_by_id=request.session.get('user_id'), adjusted_type='addition', quantity_before=before, adjusted_qty=qty, quantity_after=rm.current_stock, reason="Manual addition")
                    log_audit(request, 'STOCK_ADDED', 'RawMaterial', rm.id, new_val={'qty': float(qty)})
                    _invalidate_manager_cache()
                    message, message_type = f"Added {qty} {rm.units} to {rm.name}.", "success"
            except Exception as e: message, message_type = f"Error: {str(e)}", "error"
        elif action == 'log_wastage':
            try:
                material_id = request.POST.get('material_id')
                qty = Decimal(request.POST.get('quantity', '0') or '0')
                reason = request.POST.get('reason', 'Wastage')
                if not material_id: message, message_type = "Please select a material.", "error"
                else:
                    if qty <= 0:
                        raise ValueError("Quantity must be > 0.")
                    with transaction.atomic():
                        rm = RawMaterial.objects.select_for_update().get(id=material_id)
                        if rm.current_stock < qty:
                            raise ValueError("Not enough stock.")
                        before = rm.current_stock
                        rm.current_stock -= qty
                        rm.save()
                        StockAdjustment.objects.create(raw_material=rm, adjusted_by_id=request.session.get('user_id'), adjusted_type='wastage', quantity_before=before, adjusted_qty=qty, quantity_after=rm.current_stock, reason=reason)
                    log_audit(request, 'WASTAGE_LOGGED', 'RawMaterial', rm.id, new_val={'qty': float(qty), 'reason': reason})
                    _invalidate_manager_cache()
                    message, message_type = f"Logged {qty} {rm.units} wastage for {rm.name}. New stock: {rm.current_stock} {rm.units}", "success"
            except Exception as e: message, message_type = f"Error: {str(e)}", "error"
        elif action == 'update_cost':
            try:
                material_id = request.POST.get('material_id')
                new_cost_str = request.POST.get('new_cost', '').strip()
                if not material_id:
                    message, message_type = "Select a material.", "error"
                elif not new_cost_str:
                    message, message_type = "Enter a cost value.", "error"
                else:
                    new_cost = Decimal(new_cost_str)
                    if new_cost < 0:
                        raise ValueError("Cost cannot be negative.")
                    with transaction.atomic():
                        rm = RawMaterial.objects.select_for_update().get(id=material_id)
                        old_cost = rm.cost_per_unit
                        rm.cost_per_unit = new_cost
                        rm.save(update_fields=['cost_per_unit', 'updated_at'])
                    log_audit(request, 'COST_UPDATED', 'RawMaterial', rm.id, old_val={'cost': float(old_cost)}, new_val={'cost': float(new_cost)})
                    _invalidate_manager_cache()
                    message, message_type = f"Cost for {rm.name} updated to Rs. {new_cost:.2f}.", "success"
            except Exception as e:
                message, message_type = f"Error: {str(e)}", "error"
        elif action == 'update_dish_price':
            try:
                dish_id = request.POST.get('dish_id')
                new_price = Decimal(request.POST.get('new_price', '0') or '0')
                if not dish_id: message, message_type = "Select a dish.", "error"
                else:
                    dish = Dish.objects.get(id=dish_id)
                    if new_price <= 0:
                        raise ValueError("Price must be greater than zero.")
                    if new_price < dish.cost_price:
                        raise ValueError("Price cannot be lower than the stored cost price.")
                    old_price = dish.selling_price
                    dish.selling_price = new_price
                    dish.save()
                    log_audit(request, 'PRICE_UPDATED', 'Dish', dish.id, old_val={'price': float(old_price)}, new_val={'price': float(new_price)})
                    _invalidate_manager_cache()
                    message, message_type = f"Updated {dish.name} price.", "success"
            except Exception as e: message, message_type = f"Error: {str(e)}", "error"
        active_tab = action.replace('add_stock', 'add').replace('log_wastage', 'wastage').replace('update_cost', 'cost').replace('update_dish_price', 'price')
    else:
        active_tab = 'stock'

    materials = RawMaterial.objects.filter(is_active=True).select_related('category').order_by('name')
    dishes = Dish.objects.filter(is_available=True).select_related('category').order_by('name')
    context = {
        'materials': materials, 
        'dishes': dishes, 
        'message': message, 
        'message_type': message_type, 
        'manager_name': request.session.get('user_name', 'Manager'),
        'active_tab': active_tab
    }
    return render(request, 'inventory.html', context)

@cashier_required
def order_history(request):
    if 'user_id' not in request.session:
        return redirect('/login/')
    search_query = request.GET.get('search', '')
    date_filter  = request.GET.get('date', '')
    transactions = SalesTransaction.objects.all().order_by('-sale_date', '-sale_time').select_related('cashier')
    if date_filter:
        try: transactions = transactions.filter(sale_date=datetime.strptime(date_filter, "%Y-%m-%d").date())
        except ValueError: pass
    if search_query:
        transactions = transactions.filter(
            Q(transaction_no__icontains=search_query) |
            Q(cashier__full_name__icontains=search_query)
        )
    
    # Excel export
    if request.GET.get('export') == 'excel':
        from .exports import generate_orders_excel
        return generate_orders_excel(transactions, date_filter)
    
    context = {'transactions': transactions[:100], 'search_query': search_query, 'date_filter': date_filter, 'cashier_name': request.session.get('user_name', 'Unknown')}
    return render(request, 'order_history.html', context)

@manager_required
@require_POST
def void_transaction(request, txn_id):
    try:
        with transaction.atomic():
            txn = SalesTransaction.objects.select_for_update().get(id=txn_id)
            if txn.status != 'voided':
                # Historical workbook imports deliberately do not mutate stock.
                # Restoring inventory for those transactions would create stock
                # that never left the system in the first place.
                restore_stock = 'stock was not deducted' not in (txn.notes or '').lower()
                if restore_stock:
                    for item in txn.items.select_related('dish').all():
                        if item.dish:
                            for il in item.dish.ingredients.select_related('raw_material').all():
                                rm = RawMaterial.objects.select_for_update().get(id=il.raw_material_id)
                                qty_to_restore = il.quantity_required * item.quantity

                                q_before = rm.current_stock
                                rm.current_stock += qty_to_restore
                                rm.save(update_fields=['current_stock', 'updated_at'])

                                StockAdjustment.objects.create(
                                    raw_material=rm,
                                    adjusted_by_id=request.session.get('user_id'),
                                    adjusted_type='addition',
                                    quantity_before=q_before,
                                    adjusted_qty=qty_to_restore,
                                    quantity_after=rm.current_stock,
                                    reason=f"Voided Sale: {txn.transaction_no}",
                                    reference_doc=txn.transaction_no
                                )
                txn.status = 'voided'
                txn.void_reason = request.POST.get('void_reason', 'Manually voided')
                txn.save(update_fields=['status', 'void_reason'])
                log_audit(request, 'TXN_VOIDED', 'SalesTransaction', txn.id, new_val={'reason': txn.void_reason})
    except SalesTransaction.DoesNotExist:
        messages.error(request, "Transaction not found.")
    except Exception as e:
        messages.error(request, f"Error voiding transaction: {str(e)}")
    
    # Clear manager dashboard cache for today
    _invalidate_manager_cache()
    
    return redirect('/order-history/')

# --- SALES ANALYTICS DASHBOARD (FIXED) ---
@manager_required
def sales_analytics(request):
    if 'user_id' not in request.session:
        return redirect('/login/')
    local_today = timezone.localdate()
    end_date_str = request.GET.get('end_date', local_today.strftime('%Y-%m-%d'))
    start_date_str = request.GET.get('start_date', (local_today - timedelta(days=7)).strftime('%Y-%m-%d'))
    try: start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError: start_date = local_today - timedelta(days=7); start_date_str = start_date.strftime('%Y-%m-%d')
    try: end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except ValueError: end_date = local_today; end_date_str = end_date.strftime('%Y-%m-%d')
    txn_queryset = SalesTransaction.objects.filter(sale_date__range=(start_date, end_date), status='completed')
    items_queryset = SaleItem.objects.filter(transaction__sale_date__range=(start_date, end_date), transaction__status='completed')
    total_revenue = txn_queryset.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
    total_transactions = txn_queryset.count()
    total_items_sold = items_queryset.aggregate(Sum('quantity'))['quantity__sum'] or 0
    total_cogs = Decimal('0.00')
    for item in items_queryset: total_cogs += ((item.unit_cost or Decimal('0.00')) * item.quantity)
    gross_profit = total_revenue - total_cogs
    profit_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else Decimal('0.00')

    # Daily revenue trend
    daily_revenue = txn_queryset.values('sale_date').annotate(day_total=Sum('total_amount')).order_by('sale_date')
    line_labels = [dr['sale_date'].strftime('%b %d') for dr in daily_revenue]
    line_data = [float(dr['day_total']) for dr in daily_revenue]

    # Top 10 dishes by revenue
    top_dishes = items_queryset.values('dish_name').annotate(dish_revenue=Sum('line_total'), dish_qty=Sum('quantity')).order_by('-dish_revenue')[:10]
    bar_labels = [d['dish_name'] for d in top_dishes]
    bar_data = [float(d['dish_revenue']) for d in top_dishes]

    # Top 10 dishes by quantity (NEW)
    top_dishes_qty = items_queryset.values('dish_name').annotate(dish_qty=Sum('quantity')).order_by('-dish_qty')[:10]
    qty_labels = [d['dish_name'] for d in top_dishes_qty]
    qty_data = [int(d['dish_qty']) for d in top_dishes_qty]

    # Category breakdown
    category_revenue = items_queryset.values('dish__category__name').annotate(cat_total=Sum('line_total')).order_by('-cat_total')
    pie_labels = [c['dish__category__name'] or 'Uncategorized' for c in category_revenue]
    pie_data = [float(c['cat_total']) for c in category_revenue]

    context = {
        'total_revenue': total_revenue,
        'total_transactions': total_transactions,
        'total_items_sold': total_items_sold,
        'total_cogs': total_cogs,
        'gross_profit': gross_profit,
        'profit_margin': profit_margin,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'line_labels': json.dumps(line_labels),
        'line_data': json.dumps(line_data),
        'bar_labels': json.dumps(bar_labels),
        'bar_data': json.dumps(bar_data),
        'qty_labels': json.dumps(qty_labels),
        'qty_data': json.dumps(qty_data),
        'pie_labels': json.dumps(pie_labels),
        'pie_data': json.dumps(pie_data),
        'manager_name': request.session.get('user_name', 'Manager'),
    }
    return render(request, 'analytics.html', context)

# --- KITCHEN DISPLAY SYSTEM (KDS) ---
@kitchen_required
def kitchen_display(request):
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax'):
        today = timezone.localdate()
        transactions = SalesTransaction.objects.filter(
            sale_date=today,
            status='completed',
            kitchen_status__in=['pending', 'preparing']
        ).prefetch_related('items__dish__ingredients__raw_material').order_by('kitchen_status', '-id')[:20]

        counts = SalesTransaction.objects.filter(sale_date=today, status='completed').aggregate(
            completed=Count('id', filter=Q(kitchen_status='ready')),
            preparing=Count('id', filter=Q(kitchen_status='preparing'))
        )

        # Optimization: Get all low stock material IDs in one go
        low_stock_ids = set(RawMaterial.objects.filter(
            current_stock__lte=F('reorder_level'), 
            is_active=True
        ).values_list('id', flat=True))

        kitchen_orders = []
        now_dt = timezone.localtime()
        for txn in transactions:
            items_list = []
            for item in txn.items.all():
                is_low = False
                if item.dish:
                    # Optimized check using the pre-fetched set
                    for di in item.dish.ingredients.all():
                        if di.raw_material_id in low_stock_ids:
                            is_low = True
                            break
                items_list.append({
                    'name': item.dish_name,
                    'qty': item.quantity,
                    'is_low_stock': is_low
                })
            
            sale_dt = datetime.combine(txn.sale_date, txn.sale_time)
            sale_dt = timezone.make_aware(sale_dt, timezone.get_current_timezone())
            time_diff = now_dt - sale_dt
            kitchen_orders.append({
                'id': txn.id,
                'no': txn.transaction_no,
                'time': txn.sale_time.strftime('%I:%M %p'),
                'items': items_list,
                'total': float(txn.total_amount),
                'mins_ago': int(time_diff.total_seconds() // 60),
                'kitchen_status': txn.kitchen_status,
                'order_type': txn.get_order_type_display(),
                'table_no': txn.table_no or ''
            })
        return JsonResponse({
            'orders': kitchen_orders,
            'completed_count': counts['completed'],
            'preparing_count': counts['preparing']
        })

    return render(request, 'kitchen.html')


@kitchen_required
def update_kitchen_status(request, txn_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        txn = SalesTransaction.objects.get(id=txn_id, status='completed')
    except SalesTransaction.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    new_status = request.POST.get('status', 'ready')

    if new_status in ['preparing', 'ready']:
        txn.kitchen_status = new_status
        txn.save()
        try:
            log_audit(request, 'KITCHEN_STATUS', 'SalesTransaction', txn.id,
                      new_val={'status': new_status})
        except Exception:
            pass
        return JsonResponse({'success': True, 'new_status': new_status})

    return JsonResponse({'error': 'Invalid status'}, status=400)

# --- ADD NEW DISH ---
@manager_required
def add_dish_view(request):
    if 'user_id' not in request.session: return redirect('/login/')
    message, msg_type = None, None
    categories = DishCategory.objects.filter(is_active=True)
    if request.method == 'POST':
        try:
            name = request.POST.get('name', '').strip()
            if not name: raise ValueError("Dish name is required")
            price = Decimal(request.POST.get('price', '0'))
            if price <= 0: raise ValueError("Price must be > 0")
            cat = DishCategory.objects.get(id=request.POST.get('category')) if request.POST.get('category') else None
            dish = Dish.objects.create(name=name, category=cat, selling_price=price, meal_type=request.POST.get('meal_type', 'any'), is_available=True)
            log_audit(request, 'DISH_CREATED', 'Dish', dish.id, new_val={'name': name})
            _invalidate_manager_cache()
            message, msg_type = f"'{name}' added!", "success"
        except Exception as e: message, msg_type = str(e), "error"
    return render(request, 'add_dish.html', {'categories': categories, 'message': message, 'msg_type': msg_type, 'manager_name': request.session.get('user_name')})

# --- ADD NEW RAW MATERIAL ---
@manager_required
def add_material_view(request):
    if 'user_id' not in request.session: return redirect('/login/')
    message, msg_type = None, None
    mat_categories = RawMaterialCategory.objects.all()
    if request.method == 'POST':
        try:
            name = request.POST.get('name', '').strip()
            if not name: raise ValueError("Material name is required")
            cat = RawMaterialCategory.objects.get(id=request.POST.get('category')) if request.POST.get('category') else None
            unit = request.POST.get('unit', 'kg')
            if unit not in {choice[0] for choice in RawMaterial.UNITS}:
                raise ValueError("Invalid material unit")
            cost = Decimal(request.POST.get('cost', '0') or '0')
            stock = Decimal(request.POST.get('stock', '0') or '0')
            reorder = Decimal(request.POST.get('reorder', '0') or '0')
            if cost < 0 or stock < 0 or reorder < 0:
                raise ValueError("Cost, stock, and reorder level cannot be negative")
            mat = RawMaterial.objects.create(name=name, category=cat, units=unit, cost_per_unit=cost, current_stock=stock, reorder_level=reorder)
            log_audit(request, 'MATERIAL_CREATED', 'RawMaterial', mat.id, new_val={'name': name})
            _invalidate_manager_cache()
            message, msg_type = f"'{name}' added!", "success"
        except Exception as e: message, msg_type = str(e), "error"
    return render(request, 'add_material.html', {'categories': mat_categories, 'units': RawMaterial.UNITS, 'message': message, 'msg_type': msg_type, 'manager_name': request.session.get('user_name')})

# --- VIEW AUDIT LOGS ---
@manager_required
def view_audit_logs(request):
    if 'user_id' not in request.session: return redirect('/login/')
    logs = AuditLog.objects.select_related('user').order_by('-created_at')[:500]
    if request.GET.get('export') == 'csv':
        from .exports import generate_audit_csv
        return generate_audit_csv(logs)
    return render(request, 'audit_logs.html', {'logs': logs, 'manager_name': request.session.get('user_name')})

# --- FINANCE DASHBOARD ---
@manager_required
def finance_dashboard(request):
    if 'user_id' not in request.session:
        return redirect('/login/')

    local_today = timezone.localdate()
    end_date_str   = request.GET.get('end_date',   local_today.strftime('%Y-%m-%d'))
    start_date_str = request.GET.get('start_date', (local_today - timedelta(days=29)).strftime('%Y-%m-%d'))
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    except ValueError:
        start_date = local_today - timedelta(days=29)
        start_date_str = start_date.strftime('%Y-%m-%d')
    try:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        end_date = local_today
        end_date_str = end_date.strftime('%Y-%m-%d')

    # --- Revenue ---
    txns = SalesTransaction.objects.filter(sale_date__range=(start_date, end_date), status='completed')
    total_revenue = txns.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
    total_txn_count = txns.count()

    # --- COGS ---
    sale_items = SaleItem.objects.filter(transaction__sale_date__range=(start_date, end_date), transaction__status='completed')
    total_cogs = Decimal('0.00')
    for si in sale_items:
        total_cogs += (si.unit_cost or Decimal('0.00')) * si.quantity
    gross_profit = total_revenue - total_cogs
    gross_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else Decimal('0.00')

    # --- Expenses ---
    expenses_qs = Expense.objects.filter(expense_date__range=(start_date, end_date))
    total_expenses = expenses_qs.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    net_profit = gross_profit - total_expenses
    net_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else Decimal('0.00')

    # --- Expense by Category ---
    exp_by_cat = expenses_qs.values('category__name').annotate(total=Sum('amount')).order_by('-total')
    exp_cat_labels = [e['category__name'] or 'Uncategorised' for e in exp_by_cat]
    exp_cat_data   = [float(e['total']) for e in exp_by_cat]

    # --- Sales by Category ---
    sales_by_cat_qs = sale_items.values('dish__category__name').annotate(total=Sum('line_total')).order_by('-total')
    sales_by_category = []
    for sc in sales_by_cat_qs:
        sales_by_category.append({
            'name': sc['dish__category__name'] or 'Uncategorized',
            'amount': float(sc['total']),
            'percent': float((sc['total'] / total_revenue * 100) if total_revenue > 0 else 0)
        })

    # --- Daily P&L trend ---

    daily_rev = txns.values('sale_date').annotate(day_rev=Sum('total_amount')).order_by('sale_date')
    daily_exp = expenses_qs.values('expense_date').annotate(day_exp=Sum('amount')).order_by('expense_date')
    rev_map = {r['sale_date']: float(r['day_rev']) for r in daily_rev}
    exp_map = {e['expense_date']: float(e['day_exp']) for e in daily_exp}
    all_dates = sorted(set(list(rev_map.keys()) + list(exp_map.keys())))
    trend_labels   = [d.strftime('%b %d') for d in all_dates]
    trend_revenue  = [rev_map.get(d, 0) for d in all_dates]
    trend_expenses = [exp_map.get(d, 0) for d in all_dates]
    trend_profit   = [rev_map.get(d, 0) - exp_map.get(d, 0) for d in all_dates]

    # --- Recent expenses list ---
    recent_expenses = expenses_qs.select_related('category', 'recorded_by').order_by('-expense_date', '-id')[:20]

    # --- File Export Dispatcher ---
    from .exports import generate_finance_excel
    export_format = request.GET.get('export', '')
    if export_format == 'excel':
        export_ctx = {
            'start_date': start_date_str, 'end_date': end_date_str,
            'total_revenue': total_revenue, 'total_cogs': total_cogs,
            'gross_profit': gross_profit, 'gross_margin': gross_margin,
            'total_expenses': total_expenses, 'net_profit': net_profit,
            'net_margin': net_margin, 'total_txn_count': total_txn_count,
            'sales_by_category': sales_by_category,
            'recent_expenses': recent_expenses,
            '_txns_qs': txns, '_expenses_qs': expenses_qs,
        }
        return generate_finance_excel(export_ctx)

    if export_format == 'print':
        # Render a standalone print-friendly HTML page
        print_ctx = {
            'start_date': start_date_str, 'end_date': end_date_str,
            'total_revenue': total_revenue, 'total_cogs': total_cogs,
            'gross_profit': gross_profit, 'gross_margin': gross_margin,
            'total_expenses': total_expenses, 'net_profit': net_profit,
            'net_margin': net_margin, 'total_txn_count': total_txn_count,
            'sales_by_category': sales_by_category,
            'recent_expenses': recent_expenses,
            'generated_at': __import__('datetime').datetime.now().strftime('%d %b %Y  %H:%M'),
        }
        return render(request, 'pl_report_print.html', print_ctx)





    context = {
        'start_date': start_date_str,
        'end_date': end_date_str,
        'total_revenue': total_revenue,
        'total_cogs': total_cogs,
        'gross_profit': gross_profit,
        'gross_margin': gross_margin,
        'total_expenses': total_expenses,
        'net_profit': net_profit,
        'net_margin': net_margin,
        'total_txn_count': total_txn_count,
        'recent_expenses': recent_expenses,
        'exp_cat_labels': json.dumps(exp_cat_labels),
        'exp_cat_data':   json.dumps(exp_cat_data),
        'trend_labels':   json.dumps(trend_labels),
        'trend_revenue':  json.dumps(trend_revenue),
        'trend_expenses': json.dumps(trend_expenses),
        'trend_profit':   json.dumps(trend_profit),
        'sales_by_category': sales_by_category,
        'manager_name': request.session.get('user_name', 'Manager'),
    }
    return render(request, 'finance.html', context)


@manager_required
def bulk_stock_import(request):
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        decoded_file = csv_file.read().decode('utf-8-sig')
        io_string = io.StringIO(decoded_file)
        reader = csv.DictReader(io_string)
        
        count = 0
        errors = []
        for row in reader:
            # Format: name, qty_to_add
            try:
                name = row.get('name', '').strip()
                qty = Decimal(row.get('quantity', '0'))

                if name and qty > 0:
                    # Each row gets its own savepoint so a DB error on one
                    # row does not abort the entire batch.
                    with transaction.atomic():
                        rm = RawMaterial.objects.select_for_update().get(name__iexact=name)
                        before = rm.current_stock
                        rm.current_stock += qty
                        rm.save()

                        StockAdjustment.objects.create(
                            raw_material=rm,
                            adjusted_by_id=request.session.get('user_id'),
                            adjusted_type='addition',
                            quantity_before=before,
                            adjusted_qty=qty,
                            quantity_after=rm.current_stock,
                            reason="Bulk CSV Import"
                        )
                    count += 1
            except Exception as e:
                errors.append(f"Error at '{row.get('name')}': {str(e)}")

        if count:
            _invalidate_manager_cache()
        
        return JsonResponse({'success': True, 'count': count, 'errors': errors})
    
    return JsonResponse({'error': 'Invalid request'}, status=400)


def profile_settings(request):
    if 'user_id' not in request.session:
        return redirect('/login/')

    user = get_object_or_404(User, id=request.session.get('user_id'))

    if request.method == 'POST':
        full_name = request.POST.get('full_name')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        avatar_path = request.POST.get('avatar_path')

        if new_password and new_password != confirm_password:
            return render(request, 'profile_settings.html', {'user': user, 'error': "Passwords do not match!"})
        if new_password and len(new_password) < 8:
            return render(request, 'profile_settings.html', {'user': user, 'error': "Password must be at least 8 characters long."})

        if full_name:
            user.full_name = full_name
            request.session['user_name'] = full_name

        if avatar_path:
            user.avatar_path = avatar_path
            request.session['user_avatar'] = avatar_path

        if new_password:
            # Generate salt and hash with bcrypt
            salt = bcrypt.gensalt()
            user.password_hash = bcrypt.hashpw(new_password.encode('utf-8'), salt).decode('utf-8')

        user.save()
        log_audit(request, 'USER_UPDATED_PROFILE', 'User', user.id)
        return render(request, 'profile_settings.html', {'user': user, 'success': True})

    return render(request, 'profile_settings.html', {'user': user})


@manager_required
def purchase_orders_list(request):
    pos = PurchaseOrder.objects.all().order_by('-created_at').select_related('supplier', 'ordered_by').prefetch_related('items')
    suppliers = Supplier.objects.filter(is_active=True).order_by('name')
    
    # Compute KPI stats
    from django.db.models import Count
    agg = PurchaseOrder.objects.aggregate(
        total=Count('id'),
        ordered=Count('id', filter=Q(status='ordered')),
        received=Count('id', filter=Q(status='received')),
        total_value=Sum('total_amount')
    )
    stats = {
        'total': agg['total'],
        'ordered': agg['ordered'],
        'received': agg['received'],
        'total_value': agg['total_value'] or Decimal('0.00'),
    }
    return render(request, 'purchase_orders_list.html', {'pos': pos, 'suppliers': suppliers, 'stats': stats})


@manager_required
def create_purchase_order(request):
    if request.method == 'POST':
        try:
            default_supplier_id = request.POST.get('supplier_id', '')
            notes      = request.POST.get('notes', '')
            items_json = request.POST.get('items_json')

            if not items_json:
                raise ValueError("No items in order")

            items = json.loads(items_json)
            if not items:
                raise ValueError("Please add at least one ingredient")

            user = get_object_or_404(User, id=request.session.get('user_id'))

            # ── Group items by supplier ────────────────────────────────────────
            # Each item carries supplier_id (per-row) or falls back to the
            # global default.  Items with NO supplier at all are rejected.
            from collections import defaultdict
            supplier_buckets = defaultdict(list)  # {supplier_id: [item, ...]}
            for item in items:
                sid = str(item.get('supplier_id') or default_supplier_id or '').strip()
                if not sid:
                    raise ValueError(
                        f"No supplier assigned for '{item.get('name', 'item')}'. "
                        "Please select a supplier for every ingredient."
                    )
                supplier_buckets[sid].append(item)

            created_pos = []
            timestamp   = timezone.localtime().strftime('%Y%m%d-%H%M%S')

            with transaction.atomic():
                for idx, (sid, bucket) in enumerate(supplier_buckets.items()):
                    supplier  = get_object_or_404(Supplier, id=sid)
                    po_number = f"PO-{timestamp}-{uuid4().hex[:4].upper()}-{idx+1:02d}"

                    po = PurchaseOrder.objects.create(
                        po_number   = po_number,
                        supplier    = supplier,
                        order_date  = timezone.localdate(),
                        status      = 'ordered',
                        notes       = notes,
                        ordered_by  = user,
                    )

                    total_val = Decimal('0.00')
                    for item in bucket:
                        rm         = get_object_or_404(RawMaterial, id=item['id'])
                        qty        = Decimal(str(item['qty']))
                        cost       = Decimal(str(item['cost']))
                        if qty <= 0:
                            raise ValueError(f"Quantity for {rm.name} must be greater than zero")
                        if cost < 0:
                            raise ValueError(f"Unit cost for {rm.name} cannot be negative")
                        line_total = qty * cost

                        PurchaseOrderItem.objects.create(
                            purchase_order   = po,
                            raw_material     = rm,
                            quantity_ordered = qty,
                            unit             = rm.units,
                            unit_cost        = cost,
                            line_total       = line_total,
                        )
                        total_val += line_total

                    po.total_amount = total_val
                    po.save()
                    log_audit(request, 'PO_CREATED', 'PurchaseOrder', po.id,
                              new_val={'supplier': supplier.name, 'total': float(total_val)})
                    created_pos.append({'po_id': po.id, 'po_number': po_number,
                                        'supplier': supplier.name, 'total': float(total_val)})

            return JsonResponse({
                'success': True,
                'po_count': len(created_pos),
                'orders':   created_pos,
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    suppliers = Supplier.objects.filter(is_active=True)
    low_stock = RawMaterial.objects.filter(current_stock__lte=F('reorder_level'), is_active=True)
    all_materials = RawMaterial.objects.filter(is_active=True).order_by('name').prefetch_related('dishingredient_set__dish')
    
    # Annotate each material with which dishes use it
    for m in all_materials:
        m.used_in_dishes = [di.dish.name for di in m.dishingredient_set.select_related('dish').all()[:3]]
    
    context = {
        'suppliers': suppliers,
        'low_stock': low_stock,
        'all_materials': all_materials,
        'manager_name': request.session.get('user_name', 'Manager')
    }
    return render(request, 'create_purchase_order.html', context)


@manager_required
def po_detail(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)
    items = po.items.all().select_related('raw_material')
    return render(request, 'po_detail.html', {'po': po, 'items': items})


@manager_required
def receive_purchase_order(request, po_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
        
    try:
        with transaction.atomic():
            po = PurchaseOrder.objects.select_for_update().get(id=po_id)
            if po.status == 'received':
                return JsonResponse({'error': 'PO already received'}, status=400)
            if po.status not in {'ordered', 'partially_received'}:
                return JsonResponse({'error': f"Cannot receive a PO with status '{po.status}'"}, status=400)

            for item in po.items.all():
                rm = RawMaterial.objects.select_for_update().get(id=item.raw_material_id)
                before = rm.current_stock
                rm.current_stock += item.quantity_ordered
                # Update cost_per_unit to the actual unit cost paid on this PO
                # so that future sales correctly reflect procurement cost.
                if item.unit_cost and item.unit_cost > 0:
                    rm.cost_per_unit = item.unit_cost
                rm.save(update_fields=['current_stock', 'cost_per_unit', 'updated_at'])
                item.quantity_received = item.quantity_ordered
                item.save(update_fields=['quantity_received'])

                # Log stock adjustment
                StockAdjustment.objects.create(
                    raw_material=rm,
                    adjusted_by_id=request.session.get('user_id'),
                    adjusted_type='addition',
                    quantity_before=before,
                    adjusted_qty=item.quantity_ordered,
                    quantity_after=rm.current_stock,
                    reason=f"PO Received: {po.po_number}"
                )
            
            po.status = 'received'
            po.received_by_id = request.session.get('user_id')
            po.received_date = timezone.localdate()
            po.save(update_fields=['status', 'received_by', 'received_date', 'updated_at'])
            
        log_audit(request, 'PO_RECEIVED', 'PurchaseOrder', po.id)
        _invalidate_manager_cache()
        return JsonResponse({'success': True})
    except PurchaseOrder.DoesNotExist:
        return JsonResponse({'error': 'Purchase order not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# --- SUPPLIER MANAGEMENT ---
@manager_required
def suppliers_list(request):
    if "user_id" not in request.session:
        return redirect("/login/")
    search = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "active")
    suppliers_qs = Supplier.objects.all()
    if search:
        suppliers_qs = suppliers_qs.filter(name__icontains=search)
    if status_filter == "active":
        suppliers_qs = suppliers_qs.filter(is_active=True)
    elif status_filter == "inactive":
        suppliers_qs = suppliers_qs.filter(is_active=False)
    suppliers_qs = suppliers_qs.order_by("name")
    total_outstanding = Supplier.objects.filter(is_active=True).aggregate(
        total=Sum("outstanding_balance"))["total"] or Decimal("0.00")
    context = {
        "suppliers": suppliers_qs,
        "search": search,
        "status_filter": status_filter,
        "total_suppliers": Supplier.objects.count(),
        "active_count": Supplier.objects.filter(is_active=True).count(),
        "total_outstanding": total_outstanding,
    }
    return render(request, "suppliers_list.html", context)


@manager_required
def add_edit_supplier(request, supplier_id=None):
    if "user_id" not in request.session:
        return redirect("/login/")
    instance = get_object_or_404(Supplier, id=supplier_id) if supplier_id else None
    if request.method == "POST":
        try:
            name = request.POST.get("name", "").strip()
            if not name:
                raise ValueError("Supplier name is required.")
            email = request.POST.get("email", "").strip() or None
            if email:
                try:
                    validate_email(email)
                except ValidationError as exc:
                    raise ValueError("Enter a valid supplier email address.") from exc
            data = {
                "name": name,
                "phone": request.POST.get("phone", "").strip() or None,
                "email": email,
                "contact_person": request.POST.get("contact_person", "").strip() or None,
                "street": request.POST.get("street", "").strip() or None,
                "city": request.POST.get("city", "").strip() or None,
                "zip_code": request.POST.get("zip_code", "").strip() or None,
                "payment_terms": request.POST.get("payment_terms", "").strip() or None,
                "notes": request.POST.get("notes", "").strip() or None,
                "is_active": request.POST.get("is_active") == "on",
            }
            if instance:
                for field, value in data.items():
                    setattr(instance, field, value)
                instance.save()
                log_audit(request, "SUPPLIER_UPDATED", "Supplier", instance.id, new_val={"name": name})
                return JsonResponse({"success": True, "message": "Supplier updated successfully."})
            else:
                supplier = Supplier.objects.create(**data)
                log_audit(request, "SUPPLIER_CREATED", "Supplier", supplier.id, new_val={"name": name})
                return JsonResponse({"success": True, "message": "Supplier created successfully.", "id": supplier.id})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=400)
    if instance and request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "id": instance.id, "name": instance.name,
            "phone": instance.phone or "", "email": instance.email or "",
            "contact_person": instance.contact_person or "",
            "street": instance.street or "", "city": instance.city or "",
            "zip_code": instance.zip_code or "",
            "payment_terms": instance.payment_terms or "",
            "notes": instance.notes or "", "is_active": instance.is_active,
        })
    return redirect("suppliers_list")


@manager_required
def toggle_supplier_status(request, supplier_id):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    supplier = get_object_or_404(Supplier, id=supplier_id)
    supplier.is_active = not supplier.is_active
    supplier.save()
    log_audit(request, "SUPPLIER_TOGGLED", "Supplier", supplier.id, new_val={"is_active": supplier.is_active})
    return JsonResponse({"success": True, "is_active": supplier.is_active, "name": supplier.name})


@manager_required
def delete_supplier(request, supplier_id):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    supplier = get_object_or_404(Supplier, id=supplier_id)
    if PurchaseOrder.objects.filter(supplier=supplier).exists():
        supplier.is_active = False
        supplier.save()
        return JsonResponse({"success": True, "action": "deactivated",
                             "message": "Supplier deactivated (has purchase history)."})
    supplier.delete()
    return JsonResponse({"success": True, "action": "deleted", "message": "Supplier deleted."})

@manager_required
def help_page(request):
    return render(request, "help.html")
