import os, django, sys

if os.environ.get('CANTEEN_ALLOW_DEMO_SEED', '0') != '1':
    print('Demo PO seeding is disabled. Set CANTEEN_ALLOW_DEMO_SEED=1 explicitly to run it.')
    sys.exit(1)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'canteen_config.settings')
django.setup()

from core.models import PurchaseOrder, PurchaseOrderItem, Supplier, RawMaterial, User
from datetime import datetime, date, timedelta
from decimal import Decimal

supplier = Supplier.objects.filter(is_active=True).first()
user = User.objects.filter(role='manager').first()

if not supplier:
    print('ERROR: No active supplier found')
    sys.exit(1)
if not user:
    print('ERROR: No manager user found')
    sys.exit(1)

materials = list(RawMaterial.objects.filter(is_active=True)[:5])
if not materials:
    print('ERROR: No raw materials found')
    sys.exit(1)

today = datetime.now().strftime('%Y%m%d')
for i in range(1, 4):
    po_num = f'PO-DEMO-{today}-{i:02d}'
    # Skip if already exists
    if PurchaseOrder.objects.filter(po_number=po_num).exists():
        print(f'Skipping {po_num} - already exists')
        continue

    po = PurchaseOrder.objects.create(
        po_number=po_num,
        supplier=supplier,
        order_date=date.today() - timedelta(days=i),
        status='ordered' if i < 3 else 'received',
        notes='Demo order created for testing',
        ordered_by=user,
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
    print(f'Created {po.po_number} | Supplier: {supplier.name} | Total: Rs. {total}')

print('Done.')
