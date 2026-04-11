import pyautogui
# screenWidth, screenHeight = pyautogui.size()
print(pyautogui.size())# Returns two integers, the width and height of the screen. (The primary monitor, in multi-monitor setups.)
# currentMouseX, currentMouseY = pyautogui.position()  # Returns two integers, the x and y of the mouse cursor's current position.
print(pyautogui.position())
# pyautogui.moveTo(100, 150)  # Move the mouse to the x, y coordinates 100, 150.
# pyautogui.click()  # Click the mouse at its current location.
pyautogui.moveTo(100, 150, duration=2, )
