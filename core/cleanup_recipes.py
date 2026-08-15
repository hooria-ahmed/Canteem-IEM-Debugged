import os
import sys
import django

# Set up Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'canteen_config.settings')
django.setup()

from core.models import Dish, DishIngredient

def cleanup_and_sync_recipes():
    print("Starting Recipe Sync & Cleanup...")
    
    all_dishes = list(Dish.objects.all())
    fixed_count = 0
    
    # 1. Create a map of Clean Name -> Master Dish (one that has recipes)
    recipe_map = {}
    for dish in all_dishes:
        clean_name = dish.name.strip().lower()
        ingredient_count = dish.ingredients.count()
        
        if ingredient_count > 0:
            # If we find a dish with recipes, and we don't have a master for this name yet, 
            # or this one has MORE ingredients, make it the master.
            if clean_name not in recipe_map or ingredient_count > recipe_map[clean_name].ingredients.count():
                recipe_map[clean_name] = dish

    print(f"Found {len(recipe_map)} unique master recipes.")

    # 2. Iterate again and fix dishes with 0 ingredients
    for dish in all_dishes:
        if dish.ingredients.count() == 0:
            clean_name = dish.name.strip().lower()
            if clean_name in recipe_map:
                master = recipe_map[clean_name]
                if master.id != dish.id:
                    print(f"Syncing: '{dish.name}' (ID {dish.id}) <- '{master.name}' (ID {master.id})")
                    
                    # Copy ingredients
                    for ing in master.ingredients.all():
                        DishIngredient.objects.get_or_create(
                            dish=dish,
                            raw_material=ing.raw_material,
                            defaults={
                                'quantity_required': ing.quantity_required,
                                'unit': ing.unit
                            }
                        )
                    fixed_count += 1

    print(f"\nSuccessfully synced recipes for {fixed_count} dishes!")

if __name__ == "__main__":
    cleanup_and_sync_recipes()
