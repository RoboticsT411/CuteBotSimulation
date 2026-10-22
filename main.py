from microbit import *

car_address = 0x010  # I2C address for the car
pinL = pin13  # Left line tracking sensor
pinR = pin14  # Right line tracking sensor

def motors_speed(left_wheel_speed, right_wheel_speed):
    """
    Set the speed and direction of the car's motors.

    :param left_wheel_speed: Speed for the left wheel (-100 to 100)
    :param right_wheel_speed: Speed for the right wheel (-100 to 100)
    """
    # Determine the direction for each wheel
    left_direction = 0x02 if left_wheel_speed > 0 else 0x01
    right_direction = 0x02 if right_wheel_speed > 0 else 0x01

    # Ensure the speed is positive
    left_wheel_speed = abs(left_wheel_speed)
    right_wheel_speed = abs(right_wheel_speed)

    # Send the speed and direction to the car via I2C
    i2c.write(car_address, bytearray([0x01, left_direction, left_wheel_speed, 0]))
    i2c.write(car_address, bytearray([0x02, right_direction, right_wheel_speed, 0]))

def get_tracking():
    """
    Get the status of the line tracking sensors.

    :return: A code representing the sensor status
    """
    left = pinL.read_digital()
    right = pinR.read_digital()
    if left == 1 and right == 1:
        return 0
    elif left == 0 and right == 1:
        return 10
    elif left == 1 and right == 0:
        return 1
    elif left == 0 and right == 0:
        return 11
    else:
        print("Unknown ERROR")

while True:
    i = get_tracking()
    if i == 10:
        motors_speed(10, 50)  # Turn right
        display.show(Image.HAPPY)
    if i == 1:
        motors_speed(50, 10)  # Turn left
        display.show(Image.SAD)
    if i == 11:
        motors_speed(25, 25)  # Move forward
