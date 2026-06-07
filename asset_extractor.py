import os

import cv2
import mss
import numpy as np


def main() -> None:
    templates_dir = 'templates'
    os.makedirs(templates_dir, exist_ok=True)

    capture_region = {'top': 150, 'left': -1600, 'width': 1280, 'height': 850}
    with mss.mss() as screen_capture:
        shot = screen_capture.grab(capture_region)
        frame = np.array(shot)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    while True:
        print('\nDrag a tight ROI around a single card rank, then press ENTER.')
        roi = cv2.selectROI('Extractor', frame, showCrosshair=True, fromCenter=False)
        x, y, w, h = roi
        if w == 0 or h == 0:
            print('No ROI selected. Try again or type quit at the prompt to quit.')
            cv2.destroyWindow('Extractor')
            answer = input("Enter rank for this template (e.g., A, K, Q, J, T, 9) or 'quit' to exit: ").strip()
            if answer.lower() == 'quit':
                break
            continue

        rank = input("Enter rank for this template (e.g., A, K, Q, J, T, 9) or 'quit' to exit: ").strip()
        if rank.lower() == 'quit':
            break

        rank = rank.upper()
        crop = frame[y:y + h, x:x + w]
        gray_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        output_path = os.path.join(templates_dir, f'{rank}.png')
        cv2.imwrite(output_path, gray_crop)
        print(f'Saved template: {output_path}')

    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
