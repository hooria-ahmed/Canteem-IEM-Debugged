from datetime import time
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Dish,
    DishIngredient,
    MealSession,
    PurchaseOrder,
    PurchaseOrderItem,
    RawMaterial,
    SaleItem,
    SalesTransaction,
    StockAdjustment,
    Supplier,
    User,
)


class CanteenWorkflowTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create(
            user_name='manager_test',
            password_hash='unused',
            full_name='Manager Test',
            role='manager',
        )
        self.cashier = User.objects.create(
            user_name='cashier_test',
            password_hash='unused',
            full_name='Cashier Test',
            role='cashier',
        )
        self.kitchen = User.objects.create(
            user_name='kitchen_test',
            password_hash='unused',
            full_name='Kitchen Test',
            role='kitchen',
        )
        self.admin_user = User.objects.create(
            user_name='admin_test',
            password_hash='unused',
            full_name='Admin Test',
            role='admin',
        )
        self.meal_session = MealSession.objects.create(
            name='lunch',
            start_time=time(0, 0),
            end_time=time(23, 59),
            is_active=True,
        )
        self.material = RawMaterial.objects.create(
            name='Test Material',
            units='kg',
            current_stock=Decimal('10.000'),
            cost_per_unit=Decimal('20.0000'),
            reorder_level=Decimal('1.000'),
            reorder_quantity=Decimal('2.000'),
        )
        self.dish = Dish.objects.create(
            name='Test Dish',
            selling_price=Decimal('99.50'),
            cost_price=Decimal('2.00'),
        )
        DishIngredient.objects.create(
            dish=self.dish,
            raw_material=self.material,
            quantity_required=Decimal('0.1000'),
            unit='kg',
        )

    def login_session(self, user):
        client = Client()
        session = client.session
        session['user_id'] = user.id
        session['user_name'] = user.full_name
        session['user_role'] = user.role
        session.save()
        return client

    def make_sale(self, transaction_no, notes=None):
        txn = SalesTransaction.objects.create(
            transaction_no=transaction_no,
            cashier=self.cashier,
            meal_session=self.meal_session,
            sale_date=timezone.localdate(),
            sale_time=time(12, 0),
            sub_total=Decimal('99.50'),
            total_amount=Decimal('99.50'),
            amount_received=Decimal('100.00'),
            change_returned=Decimal('0.50'),
            payment_method='cash',
            status='completed',
            notes=notes,
        )
        SaleItem.objects.create(
            transaction=txn,
            dish=self.dish,
            dish_name=self.dish.name,
            quantity=1,
            unit_price=Decimal('99.50'),
            unit_cost=Decimal('2.00'),
            line_total=Decimal('99.50'),
        )
        return txn

    def test_role_guards_allow_admin_manager_and_block_cashier(self):
        self.assertEqual(self.login_session(self.manager).get('/manager/').status_code, 200)
        self.assertEqual(self.login_session(self.admin_user).get('/manager/').status_code, 200)
        self.assertEqual(self.login_session(self.cashier).get('/manager/').status_code, 302)
        self.assertEqual(self.login_session(self.kitchen).get('/add-dish/').status_code, 302)

    def test_checkout_preserves_decimal_money_and_deducts_stock(self):
        client = self.login_session(self.cashier)
        session = client.session
        session['cart'] = {str(self.dish.id): {'qty': 1}}
        session.save()

        response = client.post(
            reverse('process_checkout'),
            {'amount_received': '100.00', 'payment_method': 'cash', 'order_type': 'dine_in'},
        )
        self.assertEqual(response.status_code, 302)

        txn = SalesTransaction.objects.get(transaction_no__startswith='WEB-')
        self.assertEqual(txn.total_amount, Decimal('99.50'))
        self.assertEqual(txn.change_returned, Decimal('0.50'))
        self.material.refresh_from_db()
        self.dish.refresh_from_db()
        self.assertEqual(self.material.current_stock, Decimal('9.900'))
        self.assertEqual(self.dish.total_sold, 1)

    def test_checkout_rejects_insufficient_cash_without_creating_sale(self):
        client = self.login_session(self.cashier)
        session = client.session
        session['cart'] = {str(self.dish.id): {'qty': 1}}
        session.save()

        response = client.post(
            reverse('process_checkout'),
            {'amount_received': '50.00', 'payment_method': 'cash'},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SalesTransaction.objects.count(), 0)
        self.material.refresh_from_db()
        self.assertEqual(self.material.current_stock, Decimal('10.000'))

    def test_void_requires_post_and_restores_live_sale_inventory_once(self):
        txn = self.make_sale('WEB-VOID-TEST')
        self.material.current_stock = Decimal('9.900')
        self.material.save(update_fields=['current_stock'])
        client = self.login_session(self.manager)

        self.assertEqual(client.get(reverse('void_transaction', args=[txn.id])).status_code, 405)
        self.material.refresh_from_db()
        self.assertEqual(self.material.current_stock, Decimal('9.900'))

        response = client.post(reverse('void_transaction', args=[txn.id]), {'void_reason': 'test'})
        self.assertEqual(response.status_code, 302)
        txn.refresh_from_db()
        self.material.refresh_from_db()
        self.assertEqual(txn.status, 'voided')
        self.assertEqual(self.material.current_stock, Decimal('10.000'))
        self.assertEqual(StockAdjustment.objects.filter(reference_doc=txn.transaction_no).count(), 1)

        client.post(reverse('void_transaction', args=[txn.id]), {'void_reason': 'again'})
        self.material.refresh_from_db()
        self.assertEqual(self.material.current_stock, Decimal('10.000'))

    def test_void_imported_sale_does_not_create_stock(self):
        txn = self.make_sale(
            'IMP-20260101-0001-1',
            notes='Imported historical sale; stock was not deducted by this import.',
        )
        client = self.login_session(self.manager)
        response = client.post(reverse('void_transaction', args=[txn.id]), {'void_reason': 'bad import'})

        self.assertEqual(response.status_code, 302)
        txn.refresh_from_db()
        self.material.refresh_from_db()
        self.assertEqual(txn.status, 'voided')
        self.assertEqual(self.material.current_stock, Decimal('10.000'))
        self.assertFalse(StockAdjustment.objects.filter(reference_doc=txn.transaction_no).exists())

    def test_purchase_order_receipt_updates_stock_only_once(self):
        supplier = Supplier.objects.create(name='Test Supplier')
        po = PurchaseOrder.objects.create(
            po_number='PO-TEST-001',
            supplier=supplier,
            ordered_by=self.manager,
            order_date=timezone.localdate(),
            status='ordered',
            total_amount=Decimal('40.00'),
        )
        item = PurchaseOrderItem.objects.create(
            purchase_order=po,
            raw_material=self.material,
            quantity_ordered=Decimal('2.000'),
            unit='kg',
            unit_cost=Decimal('20.0000'),
            line_total=Decimal('40.00'),
        )
        client = self.login_session(self.manager)

        response = client.post(reverse('receive_purchase_order', args=[po.id]))
        self.assertEqual(response.status_code, 200)
        self.material.refresh_from_db()
        po.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(self.material.current_stock, Decimal('12.000'))
        self.assertEqual(po.status, 'received')
        self.assertEqual(po.received_by_id, self.manager.id)
        self.assertEqual(item.quantity_received, Decimal('2.000'))

        response = client.post(reverse('receive_purchase_order', args=[po.id]))
        self.assertEqual(response.status_code, 400)
        self.material.refresh_from_db()
        self.assertEqual(self.material.current_stock, Decimal('12.000'))

    def test_supplier_rejects_malformed_email(self):
        client = self.login_session(self.manager)
        response = client.post(reverse('add_supplier'), {'name': 'Bad Email Supplier', 'email': 'not-an-email'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Supplier.objects.filter(name='Bad Email Supplier').exists())

    def test_daily_report_route_is_reachable_for_manager(self):
        client = self.login_session(self.manager)
        response = client.get(reverse('daily_report'))
        self.assertEqual(response.status_code, 200)

    def test_daily_report_recalculates_and_separates_gross_from_net(self):
        txn = self.make_sale('WEB-REPORT-TEST')
        txn.sub_total = Decimal('110.00')
        txn.discount_amount = Decimal('10.00')
        txn.total_amount = Decimal('100.00')
        txn.amount_received = Decimal('100.00')
        txn.change_returned = Decimal('0.00')
        txn.save()

        client = self.login_session(self.manager)
        client.get(reverse('daily_report'))
        from .models import DailyReport
        report = DailyReport.objects.get(report_date=timezone.localdate())
        self.assertEqual(report.gross_revenue, Decimal('110.00'))
        self.assertEqual(report.total_discounts, Decimal('10.00'))
        self.assertEqual(report.net_revenue, Decimal('100.00'))
        self.assertEqual(report.generated_by_id, self.manager.id)

        txn.total_amount = Decimal('90.00')
        txn.amount_received = Decimal('90.00')
        txn.save()
        client.get(reverse('daily_report'))
        report.refresh_from_db()
        self.assertEqual(report.net_revenue, Decimal('90.00'))
