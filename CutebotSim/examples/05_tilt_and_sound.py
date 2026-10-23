# Accelerometer, microphone and speaker. Open the simulator's Sensors tab:
# - drag the dot on the tilt pad: the display shows which way the micro:bit is tilted
# - press Shake: a surprised face
# - press Clap (or raise the Microphone slider): a short tune plays
from microbit import *
import music

while True:
    if accelerometer.was_gesture("shake"):
        display.show(Image.SURPRISED)
        sleep(500)

    if microphone.was_event(SoundEvent.LOUD):
        display.show(Image.MUSIC_QUAVERS)
        music.play(["c5:2", "e", "g:4"])

    x = accelerometer.get_x()          # + = right edge down
    y = accelerometer.get_y()          # + = logo edge down
    if x > 300:
        display.show(Image.ARROW_E)
    elif x < -300:
        display.show(Image.ARROW_W)
    elif y > 300:
        display.show(Image.ARROW_N)
    elif y < -300:
        display.show(Image.ARROW_S)
    else:
        display.show(Image.SQUARE_SMALL)
    sleep(100)
