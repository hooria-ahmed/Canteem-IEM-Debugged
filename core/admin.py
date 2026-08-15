from django.contrib import admin
from .models import (
    DishCategory, Dish, 
    RawMaterialCategory, RawMaterial, DishIngredient,
    User, Admin, Manager, Cashier,
    MealSession, Supplier, ExpenseCategory,
    PurchaseOrder, PurchaseOrderItem,
    Expense,
    SalesTransaction, SaleItem,
    StockAdjustment, DailyReport, AuditLog
)

# Register them all
admin.site.register(DishCategory)
admin.site.register(Dish)
admin.site.register(RawMaterialCategory)
admin.site.register(RawMaterial)
admin.site.register(DishIngredient)

# Users (Django will display them nicely because of inheritance)
admin.site.register(User)
admin.site.register(Admin)
admin.site.register(Manager)
admin.site.register(Cashier)

admin.site.register(MealSession)
admin.site.register(Supplier)
admin.site.register(ExpenseCategory)
admin.site.register(PurchaseOrder)
admin.site.register(PurchaseOrderItem)
admin.site.register(Expense)
admin.site.register(SalesTransaction)
admin.site.register(SaleItem)
admin.site.register(StockAdjustment)
admin.site.register(DailyReport)
admin.site.register(AuditLog)