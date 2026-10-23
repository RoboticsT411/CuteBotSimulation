from microbit import *

car_address=0x010
pinL = pin13
pinR = pin14

def motors_speed(left_wheel_speed,right_wheel_speed):

    left_direction = 0x02 if left_wheel_speed > 0 else 0x01
    right_direction = 0x02 if right_wheel_speed > 0 else 0x01

    left_wheel_speed = left_wheel_speed if left_wheel_speed > 0 else left_wheel_speed * -1
    right_wheel_speed = right_wheel_speed if right_wheel_speed > 0 else right_wheel_speed * -1


    i2c.write(car_address, bytearray([0x01, left_direction, left_wheel_speed, 0]))

    i2c.write(car_address, bytearray([0x02, right_direction, right_wheel_speed, 0]))


# noinspection MicroPythonRequirements
def get_tracking():

    left = pinL.read_digital()
    right = pinR.read_digital()
    if left == 1 and right == 1:
        return 00
    elif left == 0 and right == 1:
        return 10
    elif left == 1 and right == 0:
        return 1
    elif left == 0 and right == 0:
        return 11
    else:
        print("Unknown ERROR")



while(True):

    i = get_tracking()
    if i == 10:
        motors_speed(10, 50)
    if i == 1:

        motors_speed(50, 10)
    if i == 11:
        motors_speed(25, 25)
