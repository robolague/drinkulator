#! python3
import kivy
from kivy.app import App
from kivy.uix.label import Label
from kivy.uix.gridlayout import GridLayout
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.uix.button import Button
from kivy.uix.boxlayout import BoxLayout
from kivy.properties import ListProperty
from kivy.uix.screenmanager import ScreenManager, Screen
import time

sm = ScreenManager()


class SplashScreen(GridLayout):
	def __init__(self,**kwargs):
		super(SplashScreen,self).__init__(**kwargs)
		self.cols = 1
		self.add_widget(Label(text="5 Gallon Converter"))



class LoginScreen(GridLayout):
	def __init__(self,**kwargs):
		super(LoginScreen,self).__init__(**kwargs)
		self.cols = 2
		self.add_widget(Label(text='User Name'))
		self.username = TextInput(multiline=False)
		self.add_widget(self.username)
		self.add_widget(Label(text="Password"))
		self.password = TextInput(password=True,multiline=False)
		self.add_widget(self.password)

class MyApp(App):
	def build(self):
		return SplashScreen()
		time.sleep(5)
		SplashScreen.clear_widgets()

if __name__ == '__main__':
	MyApp().run()

#drinkulator - original calculations by Greg Miller (tenadar.com)

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
one_5gal = 18927.1
ingredients = {}
sum_of_ingredients = 0

number_of_ingredients = int(input("How many ingredients? "))


for number in range(number_of_ingredients):
	name_of_ingredient = input("Name of ingredient: ")
	amount_of_ingredient = float(input("Amount of ingredient: "))
	measurement_of_ingredient =  input("Measurement of ingredient (mL, Oz, Tbsp, Tsp, L, shots, handles, cups, gallons, quarts: ")
	measurement_of_ingredient = measurement_of_ingredient.lower()
	if measurement_of_ingredient == "ml":
		pass
	elif measurement_of_ingredient == 'oz':
		amount_of_ingredient = amount_of_ingredient * one_oz
	elif measurement_of_ingredient == 'tbsp':
		amount_of_ingredient = amount_of_ingredient * one_tbsp
	elif measurement_of_ingredient == 'tsp':
		amount_of_ingredient = amount_of_ingredient * one_tsp
	elif measurement_of_ingredient == 'liters':
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

	ingredients[name_of_ingredient]=amount_of_ingredient

for key,value in ingredients.items():
	sum_of_ingredients = sum_of_ingredients + value
	multiply_by = one_5gal / sum_of_ingredients

for key,value in ingredients.items():
	value = multiply_by * value

	measurement_of_output =  input("Measurement of output (mL, Oz, Tbsp, Tsp, L, shots, handles, cups, gallons, quarts: ")
	measurement_of_output = measurement_of_output.lower()
	if measurement_of_output == "ml":
		pass
	elif measurement_of_output == 'oz':
		amount_of_ingredient = value / one_oz
	elif measurement_of_output == 'tbsp':
		amount_of_ingredient = value / one_tbsp
	elif measurement_of_output == 'tsp':
		amount_of_ingredient = value / one_tsp
	elif measurement_of_output == 'liters':
		amount_of_ingredient = value / one_liter
	elif measurement_of_output == 'shots':
		amount_of_ingredient = value / one_shot
	elif measurement_of_output == 'handles':
		amount_of_ingredient = value / one_handle
	elif measurement_of_output == 'cups':
		amount_of_ingredient = value / one_cup
	elif measurement_of_output == 'gallons':
		amount_of_ingredient = value / one_gallon
	elif measurement_of_output == 'quarts':
		amount_of_ingredient = value / one_quart
	else:
		print("Not a valid measurement")

	print("Ingredient: " + key, "Amount: " + str(amount_of_ingredient),measurement_of_output)

