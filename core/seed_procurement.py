from decimal import Decimal
from datetime import datetime, timedelta
import os
import random
from core.models import User, Supplier, RawMaterial, RawMaterialCategory, PurchaseOrder, PurchaseOrderItem, StockAdjustment

def seed_fake_procurement_data():
    """
    Checks if procurement data (Purchase Orders) exists.
    If not, seeds realistic high-quality fake data including
    Suppliers, Raw Materials, Purchase Orders, Items, and Stock Adjustments.
    """
    if os.environ.get('CANTEEN_ALLOW_DEMO_SEED', '0') != '1':
        print("[Seed] Demo seeding is disabled. Set CANTEEN_ALLOW_DEMO_SEED=1 explicitly to run it.")
        return False

    # 1. Check if we already have purchase orders. If yes, skip to avoid double seeding.
    if PurchaseOrder.objects.count() > 0:
        return False

    print("[Seed] Starting procurement fake data seeding...")

    # 2. Ensure a Manager user exists to act as ordered_by / received_by
    manager = User.objects.filter(role='manager').first()
    if not manager:
        print("[Seed] Aborted: create a manager account first; demo seeding will not create a default-password user.")
        return False

    # 3. Ensure RawMaterialCategory and RawMaterials exist
    category, _ = RawMaterialCategory.objects.get_or_create(name="General")
    
    default_rm_data = [
        {"name": "Chicken Breasts", "units": "kg", "cost_per_unit": 450.00, "current_stock": 25.0, "reorder_level": 15.0},
        {"name": "Basmati Rice", "units": "kg", "cost_per_unit": 280.00, "current_stock": 10.0, "reorder_level": 30.0},
        {"name": "Cooking Oil", "units": "litre", "cost_per_unit": 380.00, "current_stock": 12.0, "reorder_level": 25.0},
        {"name": "Wheat Flour", "units": "kg", "cost_per_unit": 130.00, "current_stock": 80.0, "reorder_level": 50.0},
        {"name": "Tomatoes", "units": "kg", "cost_per_unit": 90.00, "current_stock": 5.0, "reorder_level": 15.0},
        {"name": "Onions", "units": "kg", "cost_per_unit": 80.00, "current_stock": 8.0, "reorder_level": 20.0},
        {"name": "Fresh Milk", "units": "litre", "cost_per_unit": 210.00, "current_stock": 15.0, "reorder_level": 10.0},
        {"name": "Cheddar Cheese", "units": "kg", "cost_per_unit": 1200.00, "current_stock": 3.0, "reorder_level": 5.0},
        {"name": "Sugar", "units": "kg", "cost_per_unit": 140.00, "current_stock": 40.0, "reorder_level": 20.0},
        {"name": "Green Chilies", "units": "kg", "cost_per_unit": 150.00, "current_stock": 2.0, "reorder_level": 4.0},
    ]
    
    for rm_info in default_rm_data:
        RawMaterial.objects.get_or_create(
            name=rm_info["name"],
            defaults={
                "category": category,
                "units": rm_info["units"],
                "cost_per_unit": Decimal(str(rm_info["cost_per_unit"])),
                "current_stock": Decimal(str(rm_info["current_stock"])),
                "reorder_level": Decimal(str(rm_info["reorder_level"])),
                "is_active": True
            }
        )
        
    # Re-fetch all RawMaterials to make sure we have their primary keys mapped
    all_rms = list(RawMaterial.objects.all())

    # 4. Ensure Suppliers exist
    suppliers_data = [
        {
            "name": "Metro Wholesale",
            "phone": "0300-1234567",
            "email": "metro@canteen.com",
            "contact_person": "Ali Raza",
            "street": "Main Boulevard, Gulberg",
            "city": "Lahore",
            "zip_code": "54000",
            "payment_terms": "Net 15",
            "outstanding_balance": Decimal("15500.00"),
            "notes": "Primary supplier for bulk groceries and dairy."
        },
        {
            "name": "Zenith Farms Ltd",
            "phone": "0321-7654321",
            "email": "sales@zenithfarms.pk",
            "contact_person": "Imran Khan",
            "street": "Ferozepur Road",
            "city": "Lahore",
            "zip_code": "54700",
            "payment_terms": "Cash on Delivery",
            "outstanding_balance": Decimal("42000.00"),
            "notes": "Main supplier for fresh chicken and eggs."
        },
        {
            "name": "K&N's Foods Division",
            "phone": "0312-1112223",
            "email": "wholesale@kandns.com",
            "contact_person": "Sarah Baig",
            "street": "Jail Road",
            "city": "Lahore",
            "zip_code": "54000",
            "payment_terms": "Net 30",
            "outstanding_balance": Decimal("0.00"),
            "notes": "Frozen items and premium chicken products."
        },
        {
            "name": "Fresh Agro Vegetables",
            "phone": "0333-4445556",
            "email": "agro@freshveg.pk",
            "contact_person": "Muhammad Bilal",
            "street": "Sabzi Mandi",
            "city": "Lahore",
            "zip_code": "54500",
            "payment_terms": "Weekly Settlement",
            "outstanding_balance": Decimal("8200.00"),
            "notes": "Daily fresh vegetable deliveries."
        }
    ]
    
    suppliers = []
    for s_info in suppliers_data:
        s, _ = Supplier.objects.get_or_create(
            name=s_info["name"],
            defaults={
                "phone": s_info["phone"],
                "email": s_info["email"],
                "contact_person": s_info["contact_person"],
                "street": s_info["street"],
                "city": s_info["city"],
                "zip_code": s_info["zip_code"],
                "payment_terms": s_info["payment_terms"],
                "outstanding_balance": s_info["outstanding_balance"],
                "notes": s_info["notes"],
                "is_active": True
            }
        )
        suppliers.append(s)

    # 5. Define specs for 6 different purchase orders with realistic items and dates
    po_specs = [
        {
            "offset_days": 12,
            "status": "received",
            "supplier": suppliers[0], # Metro Wholesale
            "notes": "Monthly dry grocery restocking.",
            "items": [
                {"rm_name": "Basmati Rice", "qty": 100, "cost": 275.00},
                {"rm_name": "Cooking Oil", "qty": 50, "cost": 375.00},
                {"rm_name": "Wheat Flour", "qty": 150, "cost": 125.00},
                {"rm_name": "Sugar", "qty": 50, "cost": 135.00},
            ]
        },
        {
            "offset_days": 8,
            "status": "received",
            "supplier": suppliers[1], # Zenith Farms Ltd
            "notes": "Weekly chicken and egg supply.",
            "items": [
                {"rm_name": "Chicken Breasts", "qty": 80, "cost": 440.00},
                {"rm_name": "Fresh Milk", "qty": 60, "cost": 205.00},
            ]
        },
        {
            "offset_days": 4,
            "status": "ordered",
            "supplier": suppliers[3], # Fresh Agro Vegetables
            "notes": "Emergency vegetable stock replenishment.",
            "items": [
                {"rm_name": "Tomatoes", "qty": 30, "cost": 85.00},
                {"rm_name": "Onions", "qty": 40, "cost": 75.00},
                {"rm_name": "Green Chilies", "qty": 10, "cost": 140.00},
            ]
        },
        {
            "offset_days": 2,
            "status": "ordered",
            "supplier": suppliers[2], # K&N's Foods Division
            "notes": "Stocking up for the upcoming weekend event.",
            "items": [
                {"rm_name": "Chicken Breasts", "qty": 120, "cost": 450.00},
                {"rm_name": "Cheddar Cheese", "qty": 15, "cost": 1180.00},
            ]
        },
        {
            "offset_days": 0,
            "status": "draft",
            "supplier": suppliers[0], # Metro Wholesale
            "notes": "Draft for next month's oil and rice requirements.",
            "items": [
                {"rm_name": "Basmati Rice", "qty": 200, "cost": 280.00},
                {"rm_name": "Cooking Oil", "qty": 100, "cost": 380.00},
            ]
        },
        {
            "offset_days": 6,
            "status": "cancelled",
            "supplier": suppliers[1], # Zenith Farms Ltd
            "notes": "Cancelled due to price dispute.",
            "items": [
                {"rm_name": "Chicken Breasts", "qty": 50, "cost": 480.00},
            ]
        }
    ]

    # 6. Create the Purchase Orders and Items
    for idx, spec in enumerate(po_specs):
        order_date = datetime.now().date() - timedelta(days=spec["offset_days"])
        expected_date = order_date + timedelta(days=2)
        received_date = order_date + timedelta(days=1) if spec["status"] == "received" else None
        
        po_number = f"PO-{order_date.strftime('%Y%m%d')}-{idx + 1:03d}"
        
        if PurchaseOrder.objects.filter(po_number=po_number).exists():
            continue
            
        po = PurchaseOrder.objects.create(
            po_number=po_number,
            supplier=spec["supplier"],
            ordered_by=manager,
            received_by=manager if spec["status"] == "received" else None,
            order_date=order_date,
            expected_date=expected_date,
            received_date=received_date,
            status=spec["status"],
            notes=spec["notes"],
            total_amount=Decimal("0.00")
        )
        
        total_amount = Decimal("0.00")
        for item_spec in spec["items"]:
            # Find the raw material in DB
            rm = RawMaterial.objects.filter(name__iexact=item_spec["rm_name"]).first()
            if not rm:
                # Fallback to creating it
                rm = RawMaterial.objects.create(
                    name=item_spec["rm_name"],
                    category=category,
                    units="kg",
                    cost_per_unit=Decimal(str(item_spec["cost"])),
                    current_stock=Decimal("0.0"),
                    reorder_level=Decimal("10.0")
                )
                
            qty_ordered = Decimal(str(item_spec["qty"]))
            qty_received = qty_ordered if spec["status"] == "received" else Decimal("0.00")
            unit_cost = Decimal(str(item_spec["cost"]))
            line_total = qty_ordered * unit_cost
            
            PurchaseOrderItem.objects.create(
                purchase_order=po,
                raw_material=rm,
                quantity_ordered=qty_ordered,
                quantity_received=qty_received,
                unit=rm.units,
                unit_cost=unit_cost,
                line_total=line_total
            )
            
            total_amount += line_total
            
            # If status is received, simulate receiving the goods by updating stock & adding adjustment logs
            if spec["status"] == "received":
                before_stock = rm.current_stock
                rm.current_stock += qty_ordered
                rm.save()
                after_stock = rm.current_stock
                
                # Log stock adjustment
                StockAdjustment.objects.create(
                    raw_material=rm,
                    adjusted_by=manager,
                    adjusted_type='addition',
                    quantity_before=before_stock,
                    adjusted_qty=qty_ordered,
                    quantity_after=after_stock,
                    reason=f"PO Received: {po.po_number}",
                    reference_doc=po.po_number
                )
                
        po.total_amount = total_amount
        if spec["status"] == "received":
            if idx == 0:
                po.amount_paid = total_amount - Decimal("5000.00") # Some unpaid balance
            else:
                po.amount_paid = total_amount # Fully paid
        po.save()

    print("[Seed] Procurement fake data seeding completed successfully!")
    return True
