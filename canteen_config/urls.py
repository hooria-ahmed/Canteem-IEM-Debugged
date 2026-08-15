# canteen_config/urls.py
from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from core import views

urlpatterns = [
    path('admin/', admin.site.urls),  # Django admin with Jazzmin theme
    # Auth
    path('', views.login_view, name='login'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # POS & Cart
    path('pos/', views.CashierView.as_view(), name='pos'),
    path('add-to-cart/<int:dish_id>/', views.add_to_cart, name='add_to_cart'),
    path('remove-from-cart/<int:dish_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('add-to-cart-ajax/<int:dish_id>/', views.add_to_cart_ajax, name='add_to_cart_ajax'),
    path('remove-from-cart-ajax/<int:dish_id>/', views.remove_from_cart_ajax, name='remove_from_cart_ajax'),
    path('clear-cart-ajax/', views.clear_cart_ajax, name='clear_cart_ajax'),
    path('checkout-screen/', views.checkout_screen_view, name='checkout_screen'),
    path('process-checkout/', views.process_checkout, name='process_checkout'),
    path('receipt/<int:txn_id>/', views.receipt_view, name='receipt'),
    
    # Manager Dashboard
    path('manager/', views.manager_dashboard, name='manager_dashboard'),
    path('add-expense/', views.add_expense_view, name='add_expense'),
    path('manager/add-expense/', views.add_expense_view, name='add_expense_manager'),
    path('recipe-costing/', views.recipe_costing_matrix, name='recipe_costing'),
    path('inventory/', views.inventory_management, name='inventory'),
    path('sales-analytics/', views.sales_analytics, name='sales_analytics'),
    path('add-dish/', views.add_dish_view, name='add_dish'),
    path('add-material/', views.add_material_view, name='add_material'),
    path('audit-logs/', views.view_audit_logs, name='audit_logs'),
    path('bulk-stock-import/', views.bulk_stock_import, name='bulk_stock_import'),
    path('profile-settings/', views.profile_settings, name='profile_settings'),
    path('finance/', views.finance_dashboard, name='finance_dashboard'),
    path('report/', views.generate_daily_report, name='daily_report'),
    path('report/<str:report_date>/', views.generate_daily_report, name='daily_report_by_date'),
    
    # Orders
    path('order-history/', views.order_history, name='order_history'),
    path('void-transaction/<int:txn_id>/', views.void_transaction, name='void_transaction'),
    
    # Procurement (Purchase Orders)
    path('procurement/', views.purchase_orders_list, name='purchase_orders_list'),
    path('procurement/create/', views.create_purchase_order, name='create_purchase_order'),
    path('procurement/<int:po_id>/', views.po_detail, name='po_detail'),
    path('procurement/<int:po_id>/receive/', views.receive_purchase_order, name='receive_purchase_order'),

    # Supplier Management
    path('suppliers/', views.suppliers_list, name='suppliers_list'),
    path('suppliers/add/', views.add_edit_supplier, name='add_supplier'),
    path('suppliers/<int:supplier_id>/edit/', views.add_edit_supplier, name='edit_supplier'),
    path('suppliers/<int:supplier_id>/toggle/', views.toggle_supplier_status, name='toggle_supplier'),
    path('suppliers/<int:supplier_id>/delete/', views.delete_supplier, name='delete_supplier'),
    
    # Kitchen KDS
    path('kitchen/', views.kitchen_display, name='kitchen_display'),
    path('kitchen/update-status/<int:txn_id>/', views.update_kitchen_status, name='update_kitchen_status'),
    
    # Error Pages
    path('400/', views.custom_400),
    path('404/', views.custom_404),
    path('500/', views.custom_500),

    # Help
    path('help/', views.help_page, name='help_page'),
]

# Custom error handlers
handler400 = views.custom_400
handler404 = views.custom_404
handler500 = views.custom_500

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)