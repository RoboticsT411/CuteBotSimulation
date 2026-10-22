from microbit import *

# Define a function to display an image
def display_image(image):
    display.show(image)
    sleep(1000)

# Call the function with different images
display_image(Image.HEART)
display_image(Image.HAPPY)
display_image(Image.SAD)

# Define a function to check button presses and display an image
def check_buttons():
    if button_a.is_pressed():
        display.show(Image.HAPPY)
    elif button_b.is_pressed():
        display.show(Image.SAD)
    else:
        display.show(Image.ASLEEP)

# Continuously check button presses
while True:
    check_buttons()
    sleep(100)