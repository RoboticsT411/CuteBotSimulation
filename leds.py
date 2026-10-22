from microbit import *

car_address = 0x010  # I2C address for the car
left_light = 0x04  # Constant for the left light
right_light = 0x08  # Constant for the right light


def set_car_lights(light, R, G, B):
    """
    Set the color of the car lights.

    :param light: left_light=0x04, right_light=0x08
    :param R: Red intensity (0-255)
    :param G: Green intensity (0-255)
    :param B: Blue intensity (0-255)
    """
    # if R > 255 or G > 255 or B > 255:  # Ensure RGB values are within valid range
    #    raise ValueError  # Raise a ValueError if any value is out of range

    # Write the light and RGB values to the car via I2C
    i2c.write(car_address, bytearray([light, R, G, B]))


set_car_lights(left_light, 150, 120, 100)

set_car_lights(right_light, 0, 255, 0)

