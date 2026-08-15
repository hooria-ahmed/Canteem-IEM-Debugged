
from django.db import models


UNIT_CHOICES = [
    ('kg', 'Kilograms'),
    ('g', 'Grams'),
    ('litre', 'Litres'),
    ('ml', 'Millilitres'),
    ('piece', 'Pieces'),
    ('dozen', 'Dozens'),
    ('packet', 'Packets'),
    ('bag', 'Bags'),
    ('bunch', 'Bunches'),
    ('bottle', 'Bottles'),
    ('block', 'Blocks'),
    ('tin', 'Tins'),
    ('crate', 'Crates'),
    ('glass', 'Glasses'),
]

# 1. DISH_CATEGORIES (From your report Table 10)
class DishCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    sort_order = models.SmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Dish Categories"

# 2. DISHES (From your report Table 11)
class Dish(models.Model):
    # Foreign Key to DishCategory
    category = models.ForeignKey(
        DishCategory, 
        on_delete=models.PROTECT, 
        null=True, 
        blank=True
    )
    
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    
    # Decimal(10,2) from SQL = DecimalField in Django
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Enum for Meal Type
    MEAL_TYPES = [
        ('breakfast', 'Breakfast'),
        ('lunch', 'Lunch'),
        ('dinner', 'Dinner'),
        ('snack', 'Snack'),
        ('any', 'Any'),
    ]
    meal_type = models.CharField(max_length=20, choices=MEAL_TYPES, default='any')
    
    is_available = models.BooleanField(default=True, db_index=True)
    image_path = models.CharField(max_length=500, blank=True)
    total_sold = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.selling_price})"

    @property
    def stock(self):
        ingredients = self.ingredients.all()
        if not ingredients:
            return 999  # Assume unlimited if no recipe defined
        
        max_portions = []
        for item in ingredients:
            if item.quantity_required > 0:
                portions = item.raw_material.current_stock / item.quantity_required
                max_portions.append(int(portions))
            else:
                max_portions.append(0)
                
        return min(max_portions) if max_portions else 999

    class Meta:
        verbose_name_plural = "Dishes"
        constraints = [
            models.CheckConstraint(condition=models.Q(selling_price__gt=0), name='chk_dish_selling_price_positive'),
            models.CheckConstraint(condition=models.Q(selling_price__gte=models.F('cost_price')), name='chk_dish_margin_valid')
        ]

# 3. RAW_MATERIAL_CATEGORIES (From your report Table 13)
class RawMaterialCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Raw Material Categories"

# 4. RAW_MATERIALS (From your report Table 14)
class RawMaterial(models.Model):
    category = models.ForeignKey(
        RawMaterialCategory, 
        on_delete=models.PROTECT, 
        null=True, 
        blank=True
    )
    
    name = models.CharField(max_length=150)
    
    # ENUM for Units
    UNITS = UNIT_CHOICES
    units = models.CharField(max_length=20, choices=UNITS)
    
    # Decimal fields for stock and cost
    current_stock = models.DecimalField(max_digits=10, decimal_places=3, default=0.000)
    cost_per_unit = models.DecimalField(max_digits=10, decimal_places=4, default=0.0000)
    
    reorder_level = models.DecimalField(max_digits=10, decimal_places=3, default=0.000)
    reorder_quantity = models.DecimalField(max_digits=10, decimal_places=3, default=0.000)
    
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.current_stock} {self.units})"

    class Meta:
        verbose_name_plural = "Raw Materials"
        constraints = [
            models.CheckConstraint(condition=models.Q(current_stock__gte=0), name='chk_raw_material_stock_non_negative'),
            models.CheckConstraint(condition=models.Q(cost_per_unit__gte=0), name='chk_raw_material_cost_positive'),
            models.CheckConstraint(condition=models.Q(reorder_level__gte=0), name='chk_raw_material_reorder_level_positive')
        ]

# 5. DISH_INGREDIENTS (From your report Table 12 - The Recipe Bridge Table)
class DishIngredient(models.Model):
    # Links to Dish (Parent 1)
    dish = models.ForeignKey(
        Dish, 
        on_delete=models.CASCADE, 
        related_name='ingredients'
    )
    
    # Links to RawMaterial (Parent 2)
    raw_material = models.ForeignKey(
        RawMaterial, 
        on_delete=models.CASCADE
    )
    
    quantity_required = models.DecimalField(max_digits=10, decimal_places=4)
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES)
    notes = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.dish.name} needs {self.quantity_required} {self.unit} of {self.raw_material.name}"

    class Meta:
        # Enforces that you can't add the same ingredient to the same dish twice
        unique_together = ('dish', 'raw_material')
        verbose_name_plural = "Dish Ingredients"

# 6. USERS (ISA Root Table - Table 1 from Report)
# This must be defined before Admin/Manager/Cashier because they inherit from it.
class User(models.Model):
    user_name = models.CharField(max_length=60, unique=True)
    password_hash = models.CharField(max_length=255) # Stores bcrypt hash
    full_name = models.CharField(max_length=120)
    role = models.CharField(
        max_length=20, 
        choices=[('admin', 'Admin'), ('manager', 'Manager'), ('cashier', 'Cashier'), ('kitchen', 'Kitchen')]
    )
    is_active = models.BooleanField(default=True)
    avatar_path = models.CharField(max_length=500, blank=True, null=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True) # Soft delete

    def __str__(self):
        return f"{self.full_name} ({self.role})"

    class Meta:
        verbose_name_plural = "Users"

# 7. ADMIN (ISA Sub-table - Table 2 from Report)
class Admin(User):
    sys_config_access = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "Admins"

# 8. MANAGER (ISA Sub-table - Table 3 from Report)
class Manager(User):
    approval_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    department_access = models.CharField(max_length=100, default='None')

    class Meta:
        verbose_name_plural = "Managers"

# 9. CASHIER (ISA Sub-table - Table 4 from Report)
class Cashier(User):
    shift_type = models.CharField(max_length=30, default='morning')
    counter_no = models.CharField(max_length=10)

    class Meta:
        verbose_name_plural = "Cashiers"

# 10. MEAL_SESSIONS (Table 2 from Report - Independent)
class MealSession(models.Model):
    name = models.CharField(
        max_length=20, 
        choices=[('breakfast', 'Breakfast'), ('lunch', 'Lunch'), ('dinner', 'Dinner'), ('snack', 'Snack')]
    )
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Meal Sessions"

# 11. SUPPLIER (Table 5 from Report - Independent)
class Supplier(models.Model):
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, blank=True, null=True)
    email = models.EmailField(max_length=255, blank=True, null=True)
    contact_person = models.CharField(max_length=100, blank=True, null=True)
    
    # Address components (Composite Attribute in report)
    street = models.CharField(max_length=200, blank=True, null=True)
    city = models.CharField(max_length=80, blank=True, null=True)
    zip_code = models.CharField(max_length=20, blank=True, null=True)
    
    payment_terms = models.CharField(max_length=100, blank=True, null=True)
    outstanding_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Suppliers"

# 12. EXPENSE_CATEGORIES (Table 8 from Report - Independent)
class ExpenseCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Expense Categories"

# 13. PURCHASE_ORDER (Table 6 from Report - Needs Supplier & User)
class PurchaseOrder(models.Model):
    po_number = models.CharField(max_length=30, unique=True)
    
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    ordered_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='po_created')
    received_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='po_received')
    
    order_date = models.DateField()
    expected_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)
    
    status = models.CharField(
        max_length=30, 
        choices=[
            ('draft', 'Draft'), 
            ('ordered', 'Ordered'), 
            ('partially_received', 'Partially Received'), 
            ('received', 'Received'), 
            ('cancelled', 'Cancelled')
        ],
        default='draft'
    )
    
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.po_number

    class Meta:
        verbose_name_plural = "Purchase Orders"

# 14. PURCHASE_ORDER_ITEMS (Table 7 from Report - Needs PO & Raw Material)
class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    raw_material = models.ForeignKey(RawMaterial, on_delete=models.PROTECT)
    
    quantity_ordered = models.DecimalField(max_digits=10, decimal_places=3)
    quantity_received = models.DecimalField(max_digits=10, decimal_places=3, default=0.000)
    
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES)
    
    unit_cost = models.DecimalField(max_digits=10, decimal_places=4)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.raw_material.name} x {self.quantity_ordered}"

    class Meta:
        verbose_name_plural = "Purchase Order Items"

# 15. EXPENSES (Table 9 from Report - Needs Category & User)
class Expense(models.Model):
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT)
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT)
    
    title = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    expense_date = models.DateField()
    
    payment_method = models.CharField(
        max_length=20, 
        choices=[('cash', 'Cash'), ('bank_transfer', 'Bank Transfer'), ('cheque', 'Cheque'), ('online', 'Online')],
        default='cash'
    )
    
    receipt_ref = models.CharField(max_length=100, blank=True, null=True)
    receipt_image = models.CharField(max_length=500, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    is_recurring = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    class Meta:
        verbose_name_plural = "Expenses"

# 16. SALES_TRANSACTION (Table 3 from Report - Needs Cashier & Meal Session)
class SalesTransaction(models.Model):
    transaction_no = models.CharField(max_length=30, unique=True)
    
    cashier = models.ForeignKey(User, on_delete=models.PROTECT, related_name='cashier_sales')
    meal_session = models.ForeignKey(MealSession, on_delete=models.PROTECT)
    
    sale_date = models.DateField(db_index=True)
    sale_time = models.TimeField()
    
    sub_total = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    
    amount_received = models.DecimalField(max_digits=12, decimal_places=2)
    change_returned = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    payment_method = models.CharField(
        max_length=20, 
        choices=[('cash', 'Cash'), ('card', 'Card'), ('digital_wallet', 'Digital Wallet'), ('credit', 'Credit')],
        default='cash'
    )
    
    order_type = models.CharField(
        max_length=20,
        choices=[('dine_in', 'Dine-in'), ('takeaway', 'Takeaway')],
        default='dine_in'
    )
    
    table_no = models.CharField(max_length=10, blank=True, null=True)
    
    status = models.CharField(
        max_length=20, 
        choices=[('completed', 'Completed'), ('voided', 'Voided'), ('refunded', 'Refunded')],
        default='completed'
    )
    
    void_reason = models.CharField(max_length=255, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    kitchen_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('preparing', 'Preparing'),
            ('ready', 'Ready'),
        ],
        default='pending',
        db_index=True
    )   
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.transaction_no

    class Meta:
        verbose_name_plural = "Sales Transactions"
        constraints = [
            models.CheckConstraint(condition=models.Q(sub_total__gte=0), name='chk_txn_subtotal_positive'),
            models.CheckConstraint(condition=models.Q(total_amount__gte=0), name='chk_txn_total_positive'),
            models.CheckConstraint(condition=models.Q(amount_received__gte=0), name='chk_txn_amount_received_positive'),
            models.CheckConstraint(condition=models.Q(change_returned__gte=0), name='chk_txn_change_positive'),
            models.CheckConstraint(condition=models.Q(discount_amount__gte=0), name='chk_txn_discount_positive'),
            models.CheckConstraint(
                condition=~models.Q(payment_method='cash') | models.Q(amount_received__gte=models.F('total_amount')),
                name='chk_txn_cash_payment_received_sufficient'
            )
        ]

# 17. SALE_ITEM (Table 4 from Report - Needs Transaction & Dish)
class SaleItem(models.Model):
    transaction = models.ForeignKey(SalesTransaction, on_delete=models.CASCADE, related_name='items')
    dish = models.ForeignKey(Dish, on_delete=models.PROTECT)
    
    # Snapshots (as per report design)
    dish_name = models.CharField(max_length=150) # Stores name at time of sale
    quantity = models.SmallIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2) # Price snapshot
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.dish_name} x {self.quantity}"

    class Meta:
        verbose_name_plural = "Sale Items"
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gte=1), name='chk_saleitem_qty_positive'),
            models.CheckConstraint(condition=models.Q(unit_price__gt=0), name='chk_saleitem_unit_price_positive'),
            models.CheckConstraint(condition=models.Q(line_total__gte=0), name='chk_saleitem_line_total_positive')
        ]

# 18. STOCK_ADJUSTMENT (Table 15 from Report - Needs Raw Material & User)
class StockAdjustment(models.Model):
    raw_material = models.ForeignKey(RawMaterial, on_delete=models.CASCADE)
    adjusted_by = models.ForeignKey(User, on_delete=models.PROTECT)
    
    adjusted_type = models.CharField(
        max_length=20,
        choices=[('addition', 'Addition'), ('deduction', 'Deduction'), ('correction', 'Correction'), 
                 ('wastage', 'Wastage'), ('spoilage', 'Spoilage'), ('theft', 'Theft')]
    )
    
    quantity_before = models.DecimalField(max_digits=10, decimal_places=3)
    adjusted_qty = models.DecimalField(max_digits=10, decimal_places=3)
    quantity_after = models.DecimalField(max_digits=10, decimal_places=3)
    
    reason = models.CharField(max_length=300)
    reference_doc = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.raw_material.name} - {self.adjusted_type}"

    class Meta:
        verbose_name_plural = "Stock Adjustments"

# 19. DAILY_REPORT (Table 16 from Report - Needs User)
class DailyReport(models.Model):
    report_date = models.DateField(unique=True)
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    total_transactions = models.IntegerField(default=0)
    total_items_sold = models.IntegerField(default=0)
    
    gross_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    total_discounts = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    net_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    
    cost_of_goods_sold = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    gross_profit = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    
    total_expenses = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    net_profit = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    
    breakfast_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    lunch_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    snack_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report: {self.report_date}"

    class Meta:
        verbose_name_plural = "Daily Reports"

# 20. AUDIT_LOG (Table 17 from Report - Needs User)
class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action_code = models.CharField(max_length=50)
    entity_type = models.CharField(max_length=50)
    entity_id = models.IntegerField()
    
    # JSON fields require MySQL 5.7+
    old_values = models.JSONField(null=True, blank=True)
    new_values = models.JSONField(null=True, blank=True)
    
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action_code} on {self.entity_type}"

    class Meta:
        verbose_name_plural = "Audit Logs"



