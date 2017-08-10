#! python3

#ml is the default measurement. 1 ml
one_ml = 1
one_oz = 29.5735
one_tbsp = 14.7868
one_tsp = 4.92892
one_liter = 1000
one_shot = 44.3602943
one_handle = 1750
one_cup = 236.588
one_gallon = 3785.41
one_quart= 946.353
ingredients = []

number_of_ingredients = int(input("How many ingredients? "))
#if number_of_ingredients > 10:
#	print("That's just way too many ingredients.")
#else:
#	print("OK, " + str(number_of_ingredients) + " ingredients, then.")

class ingredient:
	def __init__(self, name_of_ingredient, amount_of_ingredient):
		self.name_of_ingredient = name_of_ingredient
		self.amount_of_ingredient = amount_of_ingredient
	
	def __str__(self):
		return "Name: %s, Amount: %s mL" % (self.name_of_ingredient, self.amount_of_ingredient)

	def __repr__(self):
		return "Name: %s, Amount: %s mL" % (self.name_of_ingredient, self.amount_of_ingredient)

for number in range(number_of_ingredients):
	name_of_ingredient = input("Name of ingredient: ")
	amount_of_ingredient = float(input("Amount of ingredient: "))
	measurement_of_ingredient =  input("Measurement of ingredient (mL, Oz, Tbsp, Tsp, L, shots, handles, cups, gallons, quarts: ")
	if measurement_of_ingredient == "mL":
		pass
	elif measurement_of_ingredient == 'Oz':
		amount_of_ingredient = amount_of_ingredient * one_oz
		measurement_of_ingredient = mL
	elif measurement_of_ingredient == 'Tbsp':
		amount_of_ingredient = amount_of_ingredient * one_tbsp
	elif measurement_of_ingredient == 'Tsp':
		amount_of_ingredient = amount_of_ingredient * one_tsp
	elif measurement_of_ingredient == 'Liter':
		amount_of_ingredient = amount_of_ingredient * one_liter
	elif measurement_of_ingredient == 'shots':
		amount_of_ingredient = amount_of_ingredient * one_shot
	elif measurement_of_ingredient == 'handles':
		amount_of_ingredient = amount_of_ingredient * one_handle
	elif measurement_of_ingredient == 'cups':
		amount_of_ingredient = amount_of_ingredient * one_cup
	elif measurement_of_ingredient == 'gallons':
		amount_of_ingredient = amount_of_ingredient * one_gallon
	elif measurement_of_ingredient == 'quarts':
		amount_of_ingredient = amount_of_ingredient * one_quart
	else:
		print("Not a valid measurement")

	measurement_of_ingredient = "mL"
	ingredients.append([ingredient(name_of_ingredient,amount_of_ingredient)])

print(ingredients)
