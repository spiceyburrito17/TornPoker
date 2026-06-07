import cv2
import mss
import numpy as np

CAPTURE_REGION = {'top': 150, 'left': -1600, 'width': 1280, 'height': 850}


def click_event(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        print(f"Clicked: ({x}, {y})")


def main():
    with mss.mss() as sct:
        shot = sct.grab(CAPTURE_REGION)
        frame = np.array(shot)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    window_name = 'Calibration'
    cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(window_name, click_event)
    cv2.imshow(window_name, frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
