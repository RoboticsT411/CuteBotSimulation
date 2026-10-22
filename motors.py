from microbit import *

car_address = 0x010  # I2C address for the car

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
    i2c.write(car_address, bytearray([0x02, left_direction, left_wheel_speed, 0]))
    i2c.write(car_address, bytearray([0x01, right_direction, right_wheel_speed, 0]))

# Set the speed of both motors to 25
motors_speed(25, 25)