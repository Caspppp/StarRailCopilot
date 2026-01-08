import time
import typing as t
from functools import wraps

import cv2
import numpy as np
import requests
from adbutils.errors import AdbError

from module.base.decorator import cached_property, del_cached_property
from module.base.timer import Timer
from module.device.method.uiautomator_2 import ProcessInfo, Uiautomator2
from module.device.method.utils import (
    ImageTruncated, PackageNotInstalled, RETRY_TRIES, handle_adb_error, handle_unknown_host_service, retry_sleep)
from module.exception import RequestHumanTakeover
from module.logger import logger


class DroidCastVersionIncompatible(Exception):
    pass


def retry(func):
    @wraps(func)
    def retry_wrapper(self, *args, **kwargs):
        """
        Args:
            self (Adb):
        """
        init = None
        for _ in range(RETRY_TRIES):
            try:
                if callable(init):
                    time.sleep(retry_sleep(_))
                    init()
                return func(self, *args, **kwargs)
            # Can't handle
            except RequestHumanTakeover:
                break
            # When adb server was killed
            except ConnectionResetError as e:
                logger.error(e)

                def init():
                    self.adb_reconnect()
            # AdbError
            except AdbError as e:
                if handle_adb_error(e):
                    def init():
                        self.adb_reconnect()
                elif handle_unknown_host_service(e):
                    def init():
                        self.adb_start_server()
                        self.adb_reconnect()
                else:
                    break
            # Package not installed
            except PackageNotInstalled as e:
                logger.error(e)

                def init():
                    self.detect_package()
            # DroidCast not running
            # requests.exceptions.ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
            # ReadTimeout: HTTPConnectionPool(host='127.0.0.1', port=20482): Read timed out. (read timeout=3)
            except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as e:
                logger.error(e)

                def init():
                    self.droidcast_init()
            # DroidCastVersionIncompatible
            except DroidCastVersionIncompatible as e:
                logger.error(e)

                def init():
                    self.droidcast_init()
            # ImageTruncated
            except ImageTruncated as e:
                logger.error(e)

                def init():
                    pass
            # Unknown
            except Exception as e:
                logger.exception(e)

                def init():
                    pass

        logger.critical(f'Retry {func.__name__}() failed')
        raise RequestHumanTakeover

    return retry_wrapper


class DroidCast(Uiautomator2):
    """
    DroidCast, another screenshot method, https://github.com/rayworks/DroidCast
    DroidCast_raw, a modified version of DroidCast sending raw bitmap and png, https://github.com/Torther/DroidCastS
    """

    _droidcast_port: int = 0
    droidcast_width: int = 0
    droidcast_height: int = 0
    # (mode_key, base_h, base_w, rot, flip, order)
    # flip: None, 'x' (horizontal), 'y' (vertical)
    _droidcast_raw_decode_mode: t.Optional[t.Tuple[str, int, int, int, t.Optional[str], str]] = None
    _droidcast_raw_decode_mode_orientation: t.Optional[int] = None

    @cached_property
    def droidcast_session(self):
        session = requests.Session()
        session.trust_env = False  # Ignore proxy
        self._droidcast_port = self.adb_forward('tcp:53516')
        return session

    """
    Check APIs from source code:
    https://github.com/Torther/DroidCast_raw/blob/DroidCast_raw/app/src/main/java/ink/mol/droidcast_raw/KtMain.kt
    Available APIs:
    - /screenshot
        To get a RGB565 bitmap
    - /preview
        To get PNG screenshots.
    """

    def droidcast_url(self, url='/preview'):
        if self.is_mumu_over_version_356:
            w, h = self.droidcast_width, self.droidcast_height
            if self.orientation == 0:
                return f'http://127.0.0.1:{self._droidcast_port}{url}?width={w}&height={h}'
            elif self.orientation in (1, 3):
                return f'http://127.0.0.1:{self._droidcast_port}{url}?width={h}&height={w}'
            else:
                # logger.warning('DroidCast receives invalid device orientation')
                pass

        return f'http://127.0.0.1:{self._droidcast_port}{url}'

    def droidcast_raw_url(self, url='/screenshot'):
        if self.is_mumu_over_version_356:
            w, h = self.droidcast_width, self.droidcast_height
            # MuMu12/MuMu Pro (>3.5.6) reports a vertical device with rotation.
            # Requesting a swapped (landscape) size may make some DroidCast_raw forks
            # scale the portrait frame into a landscape buffer (blurry and breaks template matching).
            # Always request the base (un-rotated) resolution and rotate locally if needed.
            if w and h:
                return f'http://127.0.0.1:{self._droidcast_port}{url}?width={w}&height={h}'

        return f'http://127.0.0.1:{self._droidcast_port}{url}'

    def droidcast_init(self):
        logger.hr('DroidCast init')
        self.droidcast_stop()
        self._droidcast_update_resolution()
        self._droidcast_raw_decode_mode = None
        self._droidcast_raw_decode_mode_orientation = None

        # Choose correct APK and main class based on version
        if self.config.DROIDCAST_VERSION == 'DroidCast_raw':
            logger.info('Pushing DroidCast_raw apk')
            self.adb_push(self.config.DROIDCAST_RAW_FILEPATH_LOCAL, self.config.DROIDCAST_RAW_FILEPATH_REMOTE)
            # Note: current bundled APK is DroidCastS (com.torther.droidcasts.*)
            # `ink.mol.droidcast_raw.Main` is for another DroidCast_raw fork and is not present in DroidCastS.
            main_class = 'com.torther.droidcasts.Main'
            classpath = self.config.DROIDCAST_RAW_FILEPATH_REMOTE
        else:
            logger.info('Pushing DroidCast apk')
            self.adb_push(self.config.DROIDCAST_FILEPATH_LOCAL, self.config.DROIDCAST_FILEPATH_REMOTE)
            main_class = 'com.rayworks.droidcast.Main'
            classpath = self.config.DROIDCAST_FILEPATH_REMOTE

        logger.info('Starting DroidCast apk')
        # Example:
        # - DroidCast:    CLASSPATH=/data/local/tmp/DroidCast.apk  app_process / com.rayworks.droidcast.Main > /dev/null
        # - DroidCastS:   CLASSPATH=/data/local/tmp/DroidCastS.apk app_process / com.torther.droidcasts.Main > /dev/null
        resp = self.u2_shell_background([
            f'CLASSPATH={classpath}',
            'app_process',
            '/',
            main_class,
            '>',
            '/dev/null'
        ])
        logger.info(resp)
        del_cached_property(self, 'droidcast_session')
        _ = self.droidcast_session

        if self.config.DROIDCAST_VERSION == 'DroidCast':
            logger.attr('DroidCast', self.droidcast_url())
            self.droidcast_wait_startup()
        elif self.config.DROIDCAST_VERSION == 'DroidCast_raw':
            logger.attr('DroidCast_raw', self.droidcast_raw_url())
            self.droidcast_wait_startup()
        else:
            logger.error(f'Unknown DROIDCAST_VERSION: {self.config.DROIDCAST_VERSION}')

    def _droidcast_update_resolution(self):
        if self.is_mumu_over_version_356:
            logger.info('Update droidcast resolution')
            w, h = self.resolution_uiautomator2(cal_rotation=False)
            self.get_orientation()
            # 720, 1280
            # mumu12 > 3.5.6 is always a vertical device
            self.droidcast_width, self.droidcast_height = w, h
            logger.info(f'Droicast resolution: {(w, h)}')

    @retry
    def screenshot_droidcast(self):
        self.config.DROIDCAST_VERSION = 'DroidCast'
        if self.is_mumu_over_version_356:
            if not self.droidcast_width or not self.droidcast_height:
                self._droidcast_update_resolution()

        resp = self.droidcast_session.get(self.droidcast_url(), timeout=3)

        if resp.status_code == 404:
            raise DroidCastVersionIncompatible('DroidCast server does not have /preview')
        image = resp.content
        image = np.frombuffer(image, np.uint8)
        if image is None:
            raise ImageTruncated('Empty image after reading from buffer')
        if image.shape == (1843200,):
            raise DroidCastVersionIncompatible('Requesting screenshots from `DroidCast` but server is `DroidCast_raw`')
        if image.size < 500:
            logger.warning(f'Unexpected screenshot: {resp.content}')

        image = cv2.imdecode(image, cv2.IMREAD_COLOR)
        if image is None:
            raise ImageTruncated('Empty image after cv2.imdecode')

        cv2.cvtColor(image, cv2.COLOR_BGR2RGB, dst=image)
        if image is None:
            raise ImageTruncated('Empty image after cv2.cvtColor')

        # Some emulators (e.g. MuMu12/MuMu Pro) report a vertical device with rotation,
        # while DroidCast may return frames in the un-rotated coordinate system.
        if self.is_mumu_over_version_356:
            if self.orientation == 1:
                image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
            elif self.orientation == 3:
                image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif self.orientation == 2:
                image = cv2.rotate(image, cv2.ROTATE_180)

        return image

    @retry
    def screenshot_droidcast_raw(self):
        self.config.DROIDCAST_VERSION = 'DroidCast_raw'
        # DroidCast_raw returns a RGB565 bitmap.
        #
        # Different emulators/forks may send the raw frame in different coordinate systems.
        # To avoid both "scrambled stripes" (wrong reshape) and "90° rotated" frames,
        # calibrate the best decode mode once (per device orientation) by comparing with uiautomator2.
        #
        # Decode mode = (base_reshape, extra_rotation)
        # - base_reshape: pick the correct (h, w) for the raw buffer
        # - extra_rotation: 0 / 90 / -90 / 180, applied after reshape
        if self.is_mumu_over_version_356:
            if not self.droidcast_width or not self.droidcast_height:
                self._droidcast_update_resolution()

        w_raw, h_raw = self.resolution_uiautomator2(cal_rotation=False)
        w_rot, h_rot = self.resolution_uiautomator2(cal_rotation=True)
        o = self.get_orientation()

        raw = self.droidcast_session.get(self.droidcast_raw_url(), timeout=3).content
        arr = np.frombuffer(raw, dtype=np.uint16)

        def rotate_2d(a: np.ndarray, rot: int, flip: t.Optional[str] = None) -> np.ndarray:
            # OpenCV assumes row-major (C-contiguous) memory.
            # ascontiguousarray preserves the logical view while ensuring C-order memory layout.
            if not a.flags['C_CONTIGUOUS']:
                a = np.ascontiguousarray(a)
            if rot == 90:
                a = cv2.transpose(a)
                a = cv2.flip(a, 1)
            elif rot == -90:
                a = cv2.transpose(a)
                a = cv2.flip(a, 0)
            elif rot == 180:
                a = cv2.flip(a, -1)
            # Apply flip after rotation
            if flip == 'x':
                a = cv2.flip(a, 1)  # Horizontal flip
            elif flip == 'y':
                a = cv2.flip(a, 0)  # Vertical flip
            return a

        def smoothness_score(a: np.ndarray) -> float:
            # Wrong reshape usually produces strong “striped” artifacts and very noisy adjacent differences.
            # Downsample for speed.
            if a.size == 0:
                return float('inf')
            s = a[::8, ::8].astype(np.int32)
            if s.shape[0] < 2 or s.shape[1] < 2:
                return float('inf')
            dh = np.mean(np.abs(np.diff(s, axis=1)))
            dv = np.mean(np.abs(np.diff(s, axis=0)))
            return float(dh + dv)

        def rgb565_to_gray_u8(a: np.ndarray) -> np.ndarray:
            # Use green channel as a cheap luminance proxy (6 bits -> 8 bits).
            # RGB565: rrrrrggggggbbbbb (g is 6-bit)
            g6 = np.bitwise_and(np.right_shift(a, 5), 0x3F).astype(np.uint16)
            g8 = (g6 * 255 + 31) // 63
            return g8.astype(np.uint8)

        # Fast path: reuse cached decode mode for the same device orientation.
        if self._droidcast_raw_decode_mode is not None and self._droidcast_raw_decode_mode_orientation == o:
            mode_key, base_h, base_w, rot, flip, order = self._droidcast_raw_decode_mode
            try:
                arr2d = arr.reshape((base_h, base_w), order=order)
                arr2d = rotate_2d(arr2d, rot, flip)
            except ValueError:
                # Resolution changed or mode became invalid, re-calibrate below.
                self._droidcast_raw_decode_mode = None
                self._droidcast_raw_decode_mode_orientation = None
            else:
                return self._rgb565_to_rgb888(arr2d)

        # Candidate base reshapes (dedup by shape + order).
        shapes: list[tuple[str, int, int, str]] = []
        seen_shapes: set[tuple[int, int, str]] = set()

        def add_shape(key: str, h: int, w: int, order: str) -> None:
            if not h or not w:
                return
            if h * w != arr.size:
                return
            shape = (h, w, order)
            if shape in seen_shapes:
                return
            seen_shapes.add(shape)
            shapes.append((key, h, w, order))

        for order in ('C', 'F'):
            add_shape('raw', h_raw, w_raw, order)
            add_shape('raw_swapped', w_raw, h_raw, order)
            add_shape('rot', h_rot, w_rot, order)
            add_shape('rot_swapped', w_rot, h_rot, order)

        base_candidates: list[tuple[str, str, np.ndarray, float]] = []
        for key, h, w, order in shapes:
            try:
                a = arr.reshape((h, w), order=order)
            except ValueError:
                continue
            base_candidates.append((key, order, a, smoothness_score(a)))

        if not base_candidates:
            if len(raw) < 500:
                logger.warning(f'Unexpected screenshot: {raw}')
            # Try to load as `DroidCast` (PNG/JPEG).
            raw_u8 = np.frombuffer(raw, np.uint8)
            decoded = cv2.imdecode(raw_u8, cv2.IMREAD_COLOR) if raw_u8 is not None else None
            if decoded is not None:
                raise DroidCastVersionIncompatible(
                    'Requesting screenshots from `DroidCast_raw` but server is `DroidCast`'
                )
            raise ImageTruncated('Unable to reshape DroidCast_raw image buffer')

        # Sort candidates by smoothness for logging, but don't filter aggressively.
        # The reference comparison will select the correct one regardless of smoothness.
        base_candidates.sort(key=lambda x: x[3])

        # Calibrate decode mode against uiautomator2 (once per orientation).
        # This picks both the correct reshape AND the required rotation, but only among
        # transformations that preserve the reference resolution (no resizing).
        try:
            ref = self.screenshot_uiautomator2()
            ref_gray = cv2.cvtColor(ref, cv2.COLOR_RGB2GRAY)[::8, ::8]
        except Exception as e:
            logger.warning(f'Failed to calibrate DroidCast_raw decode mode, fallback to smoothness: {e}')
            mode_key, order, arr2d, _ = base_candidates[0]
            rot = 0
            flip = None
            base_h, base_w = arr2d.shape[:2]
            arr2d = rotate_2d(arr2d, rot, flip)
        else:
            # Transformations: (rotation, flip)
            # flip: None, 'x' (horizontal), 'y' (vertical)
            transforms = [
                (0, None),      # No transformation
                (90, None),     # Rotate 90° CW
                (-90, None),    # Rotate 90° CCW
                (180, None),    # Rotate 180°
                (0, 'x'),       # Horizontal flip
                (0, 'y'),       # Vertical flip
                (90, 'x'),      # Rotate 90° CW + horizontal flip
                (-90, 'x'),     # Rotate 90° CCW + horizontal flip
            ]
            best: t.Optional[tuple[float, str, str, int, t.Optional[str], np.ndarray]] = None
            for key, order, a, _smooth in base_candidates:
                gray = rgb565_to_gray_u8(a)[::8, ::8]
                for rot, flip in transforms:
                    g2 = rotate_2d(gray, rot, flip)
                    if g2.shape != ref_gray.shape:
                        continue
                    score = float(np.mean(cv2.absdiff(g2, ref_gray)))
                    if best is None or score < best[0]:
                        best = (score, key, order, rot, flip, a)

            if best is None:
                # No transformation matched reference resolution; fallback to smoothest.
                mode_key, order, arr2d, _ = base_candidates[0]
                rot = 0
                flip = None
                base_h, base_w = arr2d.shape[:2]
                arr2d = rotate_2d(arr2d, rot, flip)
            else:
                score, mode_key, order, rot, flip, base_arr2d = best
                base_h, base_w = base_arr2d.shape[:2]
                arr2d = rotate_2d(base_arr2d, rot, flip)
                flip_str = f' flip={flip}' if flip else ''
                logger.attr(
                    'DroidCast_raw decode',
                    f'{mode_key}/{order} ({base_w}x{base_h}) rot={rot}{flip_str} score={score:.2f}',
                )

        self._droidcast_raw_decode_mode = (mode_key, base_h, base_w, rot, flip, order)
        self._droidcast_raw_decode_mode_orientation = o

        return self._rgb565_to_rgb888(arr2d)

    @staticmethod
    def _rgb565_to_rgb888(arr2d: np.ndarray) -> np.ndarray:
        try:
            # OpenCV assumes row-major (C-contiguous) memory.
            # ascontiguousarray preserves the logical view while ensuring C-order memory layout.
            if not arr2d.flags['C_CONTIGUOUS']:
                arr2d = np.ascontiguousarray(arr2d)
            # Convert RGB565 -> RGB888
            tmp = np.empty_like(arr2d)
            cv2.bitwise_and(arr2d, 0b1111100000000000, dst=tmp)
            r = cv2.convertScaleAbs(tmp, alpha=0.0040283203125)  # 0.00390625 * 1.03125
            cv2.bitwise_and(arr2d, 0b0000011111100000, dst=tmp)
            g = cv2.convertScaleAbs(tmp, alpha=0.126953125)  # 0.125 * 1.015625
            cv2.bitwise_and(arr2d, 0b0000000000011111, dst=tmp)
            b = cv2.convertScaleAbs(tmp, alpha=8.25)  # 8 * 1.03125
            return cv2.merge([r, g, b])
        except Exception as e:
            raise ImageTruncated(str(e)) from e

    def droidcast_wait_startup(self):
        """
        Wait until DroidCast startup completed.
        """
        timeout = Timer(10).start()
        while 1:
            self.sleep(0.25)
            if timeout.reached():
                break

            try:
                resp = self.droidcast_session.get(self.droidcast_url('/'), timeout=3)
                # Route `/` is unavailable, but 404 means startup completed
                if resp.status_code == 404:
                    logger.attr('DroidCast', 'online')
                    return True
            except requests.exceptions.ConnectionError:
                logger.attr('DroidCast', 'offline')

        logger.warning('Wait DroidCast startup timeout, assume started')
        return False

    def droidcast_uninstall(self):
        """
        Stop DroidCast processes and remove DroidCast APK.
        DroidCast hasn't been installed but a JAVA class call, uninstall is a file delete.
        """
        self.droidcast_stop()
        logger.info('Removing DroidCast')
        self.adb_shell(["rm", self.config.DROIDCAST_FILEPATH_REMOTE])

    def _iter_droidcast_proc(self) -> t.Iterable[ProcessInfo]:
        """
        List all DroidCast processes.
        """
        processes = self.proc_list_uiautomator2()
        for proc in processes:
            if 'com.rayworks.droidcast.Main' in proc.cmdline:
                yield proc
            if 'com.torther.droidcasts.Main' in proc.cmdline:
                yield proc
            if 'ink.mol.droidcast_raw.Main' in proc.cmdline:
                yield proc

    def droidcast_stop(self):
        """
        Stop DroidCast processes.
        """
        logger.info('Stopping DroidCast')
        for proc in self._iter_droidcast_proc():
            logger.info(f'Kill pid={proc.pid}')
            self.adb_shell(['kill', '-s', 9, proc.pid])
