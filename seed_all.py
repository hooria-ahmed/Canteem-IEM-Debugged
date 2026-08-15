import os
import django
import bcrypt
from decimal import Decimal

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'canteen_config.settings')
os.environ['CANTEEN_USE_SQLITE'] = '1'
os.environ['CANTEEN_ALLOW_DEMO_SEED'] = '1'
django.setup()

from core.models import User, Supplier, RawMaterial, RawMaterialCategory
from core.seed_procurement import seed_fake_procurement_data

def create_user_if_not_exists(username, password, full_name, role):
    if User.objects.filter(user_name=username).exists():
        print(f"User '{username}' already exists. Skipping.")
        return User.objects.get(user_name=username)
    
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    user = User.objects.create(
        user_name=username,
        password_hash=password_hash,
        full_name=full_name,
        role=role,
        is_active=True
    )
    print(f"Created user '{username}' with role '{role}' and password '{password}'.")
    return user

def main():
    print("Creating demo users...")
    manager = create_user_if_not_exists('manager', 'manager123', 'Demo Manager', 'manager')
    cashier = create_user_if_not_exists('cashier', 'cashier123', 'Demo Cashier', 'cashier')
    kitchen = create_user_if_not_exists('kitchen', 'kitchen123', 'Demo Kitchen', 'kitchen')
    admin = create_user_if_not_exists('admin', 'admin123', 'Demo Admin', 'admin')
    
    print("\nRunning fake procurement data seeding...")
    seed_fake_procurement_data()
    
    # Run the demo PO seed script if we have raw materials and suppliers
    print("\nChecking if demo PO seed is needed...")
    try:
        from core.models import PurchaseOrder, PurchaseOrderItem
        from datetime import date, timedelta
        
        supplier = Supplier.objects.filter(is_active=True).first()
        materials = list(RawMaterial.objects.filter(is_active=True)[:5])
        
        if supplier and materials:
            today = date.today().strftime('%Y%m%d')
            for i in range(1, 4):
                po_num = f'PO-DEMO-{today}-{i:02d}'
                if PurchaseOrder.objects.filter(po_number=po_num).exists():
                    print(f'Skipping {po_num} - already exists')
                    continue
                
                po = PurchaseOrder.objects.create(
                    po_number=po_num,
                    supplier=supplier,
                    order_date=date.today() - timedelta(days=i),
                    status='ordered' if i < 3 else 'received',
                    notes='Demo order created for testing',
                    ordered_by=manager,
                    total_amount=Decimal('0')
                )
                
                total = Decimal('0')
                for j, m in enumerate(materials[:3]):
                    qty = Decimal(str((j + 1) * 5))
                    cost = m.cost_per_unit or Decimal('100')
                    lt = qty * cost
                    PurchaseOrderItem.objects.create(
                        purchase_order=po,
                        raw_material=m,
                        quantity_ordered=qty,
                        unit=m.units,
                        unit_cost=cost,
                        line_total=lt
                    )
                    total += lt
                
                po.total_amount = total
                po.save()
                print(f'Created PO {po_num} for supplier {supplier.name}')
    except Exception as e:
        print(f"Error seeding demo POs: {e}")

if __name__ == '__main__':
    main()
