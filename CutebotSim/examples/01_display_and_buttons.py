# micro:bit display and buttons - no robot needed.
# Press A or B in the simulator (click the buttons or use the A / B keys).
from microbit import *

display.scroll("Hello LSBU")

while True:
    if button_a.was_pressed():
        display.show(Image.HAPPY)
    elif button_b.was_pressed():
        display.show(Image.SAD)
    elif button_a.is_pressed() and button_b.is_pressed():
        break
    sleep(50)

display.scroll("Bye")
