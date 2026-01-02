"""
货币战争UI识别与交互
参考 tasks/rogue/blessing/ui.py
"""
from tasks.base.ui import UI
from tasks.base.page import page_currency_war
from tasks.currency_war.assets.assets_currency_war_ui import CURRENCY_WAR_MAIN_CHECK


class CurrencyWarUI(UI):
    """
    货币战争UI识别基类
    继承 UI 以获得界面导航和模板匹配能力
    """

    def is_page_currency_war_main(self):
        """
        检查是否在货币战争主界面（难度选择界面）

        Returns:
            bool: 是否在主界面
        """
        return self.appear(CURRENCY_WAR_MAIN_CHECK)

    def is_page_currency_war_shop(self):
        """
        检查是否在商店界面（买棋子）

        Returns:
            bool: 是否在商店界面
        """
        # TODO: 实现商店界面识别
        # return self.appear(CURRENCY_WAR_SHOP_CHECK)
        return False

    def is_page_currency_war_battle(self):
        """
        检查是否在战斗界面

        Returns:
            bool: 是否在战斗界面
        """
        # TODO: 实现战斗界面识别
        # return self.appear(CURRENCY_WAR_BATTLE_CHECK)
        return False

    def get_current_coins(self):
        """
        获取当前金币数量

        Returns:
            int: 当前金币数
        """
        # TODO: 使用OCR识别金币数字
        # from module.ocr.ocr import Digit
        # return Digit(OCR_CURRENCY_WAR_COINS).ocr_single_line(self.device.image)
        return 0

    def ocr_currency_war_points(self) -> int:
        """
        OCR识别货币战争当前点数

        Returns:
            int: 当前点数 (0-18000)，识别失败返回0
        """
        from module.ocr.ocr import Digit
        from module.logger import logger
        from tasks.currency_war.assets.assets_currency_war_ui import OCR_CURRENCY_WAR_POINTS

        try:
            points = Digit(OCR_CURRENCY_WAR_POINTS).ocr_single_line(self.device.image)
            if 0 <= points <= 18000:
                logger.attr('Currency War Points', f'{points}/18000')
                return points
            else:
                logger.warning(f'OCR points out of range: {points}, assuming 0')
                return 0
        except Exception as e:
            logger.warning(f'Failed to OCR currency war points: {e}')
            return 0

    def has_reward_indicator(self) -> bool:
        """
        检测是否有奖励指示器（红点）
        优先使用模板匹配，失败再用颜色检测兜底

        Returns:
            bool: 是否存在奖励指示器
        """
        from tasks.currency_war.assets.assets_currency_war_ui import REWARD_INDICATOR

        if self.appear(REWARD_INDICATOR):
            return True

        return self.image_color_count(
            REWARD_INDICATOR,
            color=(216, 83, 82),
            threshold=200,
            count=20
        )

    def currency_war_deploy_bench_pieces_to_front(
        self,
        deploy_count: int = 3,
        wait_timeout: float = 10.0,
        wait_interval: float = 0.5,
    ) -> bool:
        """
        在超频博弈主战斗界面，将备战席位上的棋子拖到前台区域

        规则:
            1. 通过“空格子模板”判断备战席位是否有棋子
            2. 若备战席位存在相同棋子，优先只选择其中1个
            3. 将最多 `deploy_count` 个棋子拖到前台空位（优先空位）

        Returns:
            bool: 是否执行了拖动操作
        """
        import numpy as np

        from module.base.button import match_template
        from module.base.timer import Timer
        from module.base.utils import area_center, rgb2luma
        from module.logger import logger
        from tasks.currency_war.assets.assets_currency_war_ui import (
            CURRENCY_WAR_FRONT_EMPTY_1,
            CURRENCY_WAR_FRONT_EMPTY_2,
            CURRENCY_WAR_FRONT_EMPTY_3,
            CURRENCY_WAR_FRONT_EMPTY_4,
            CURRENCY_WAR_BENCH_EMPTY_1,
            CURRENCY_WAR_BENCH_PIECE_MARKER,
        )

        front_empty_buttons = [
            CURRENCY_WAR_FRONT_EMPTY_1,
            CURRENCY_WAR_FRONT_EMPTY_2,
            CURRENCY_WAR_FRONT_EMPTY_3,
            CURRENCY_WAR_FRONT_EMPTY_4,
        ]
        front_slot_areas = [
            (454, 214, 524, 306),
            (556, 214, 626, 306),
            (656, 214, 726, 306),
            (757, 214, 827, 306),
        ]

        bench_slot_areas = [
            (158 + 104 * i, 542, 254 + 104 * i, 653) for i in range(9)
        ]

        # 通过“空格子模板”判定备战席位是否为空（避免 search 过大导致误判）
        empty_tpl = CURRENCY_WAR_BENCH_EMPTY_1.buttons[0].image_luma
        inset = 10
        empty_tpl_inner = empty_tpl[inset:-inset, inset:-inset]
        empty_std_threshold = 4.0
        empty_mad_threshold = 4.0

        piece_marker_button = CURRENCY_WAR_BENCH_PIECE_MARKER.buttons[0]
        piece_marker_similarity = 0.85
        piece_marker_roi_size = (40, 50)  # (w, h) near top-right corner of slot

        def scan_bench_occupied() -> tuple[list[int], list[tuple[float, float]]]:
            occupied: list[int] = []
            stats: list[tuple[float, float]] = []
            for idx, area in enumerate(bench_slot_areas):
                slot_rgb = self.image_crop(area, copy=False)
                slot_luma = rgb2luma(slot_rgb)
                inner = slot_luma[inset:-inset, inset:-inset]

                # Off-by-one 保护（避免分辨率微抖导致 shape 不一致）
                h = min(inner.shape[0], empty_tpl_inner.shape[0])
                w = min(inner.shape[1], empty_tpl_inner.shape[1])
                inner = inner[:h, :w]
                tpl_cmp = empty_tpl_inner[:h, :w]

                mad = float(np.mean(np.abs(inner.astype(np.int16) - tpl_cmp.astype(np.int16))))
                std = float(inner.std())
                stats.append((mad, std))

                is_empty = mad <= empty_mad_threshold and std <= empty_std_threshold
                if not is_empty:
                    # 右上角白色像素标记：有标记才视为“角色棋子”，避免武器栏等干扰
                    h2, w2 = slot_rgb.shape[:2]
                    roi_w, roi_h = piece_marker_roi_size
                    roi = slot_rgb[0:min(h2, roi_h), max(0, w2 - roi_w):w2]
                    is_piece = (
                        roi.shape[0] >= piece_marker_button.image.shape[0]
                        and roi.shape[1] >= piece_marker_button.image.shape[1]
                        and piece_marker_button.match_template_luma(
                            roi, similarity=piece_marker_similarity, direct_match=True
                        )
                    )
                    if is_piece:
                        occupied.append(idx)

            return occupied, stats

        occupied_bench: list[int] = []
        last_bench_stats: list[tuple[float, float]] = []

        logger.info('Waiting for pieces to land on bench...')
        wait_timer = Timer(wait_timeout).start()
        stable_frames = 0
        stable_count_frames = 0
        max_count_seen = 0
        prev_count = 0
        prev_occupied: set[int] = set()

        while not wait_timer.reached():
            self.device.screenshot()
            occupied_bench, last_bench_stats = scan_bench_occupied()
            occupied_set = set(occupied_bench)

            if occupied_set:
                count = len(occupied_bench)
                if count > max_count_seen:
                    max_count_seen = count
                    stable_count_frames = 0
                elif count == prev_count and prev_occupied and (occupied_set & prev_occupied):
                    stable_count_frames += 1
                else:
                    stable_count_frames = 0

                stable_frames = stable_frames + 1 if (prev_occupied and (occupied_set & prev_occupied)) else 1
                prev_occupied = occupied_set
                prev_count = count

                if stable_frames >= 2 and count >= deploy_count:
                    break

                # 数量不再增长时提前结束等待（避免一直等不到 deploy_count）
                if max_count_seen > 0 and stable_count_frames >= 2 and count == max_count_seen:
                    break
            else:
                stable_frames = 0
                stable_count_frames = 0
                max_count_seen = 0
                prev_count = 0
                prev_occupied = set()

            self.device.sleep(wait_interval)

        if not occupied_bench:
            logger.info('No pieces on bench detected, skip deploy')
            logger.info(
                'Bench slot stats(mad,std)='
                f'{[(i + 1, round(mad, 1), round(std, 1)) for i, (mad, std) in enumerate(last_bench_stats)]}'
            )
            return False

        # 1) 找前台空位
        empty_front: list[int] = []
        for idx, btn in enumerate(front_empty_buttons):
            if self.match_template_luma(btn, similarity=0.8):
                empty_front.append(idx)
        if not empty_front:
            logger.info('No empty front slot detected, skip deploy')
            return False

        # 3) 去重：通过棋子截图相似度判断“同一棋子”
        unique_bench = []
        unique_lumas = []

        for idx in occupied_bench:
            x1, y1, x2, y2 = bench_slot_areas[idx]
            inner = (x1 + 10, y1 + 10, x2 - 10, y2 - 10)
            piece_luma = rgb2luma(self.image_crop(inner, copy=False))

            duplicated = False
            for rep in unique_lumas:
                if match_template(piece_luma, rep, similarity=0.9):
                    duplicated = True
                    break

            if duplicated:
                continue

            unique_bench.append(idx)
            unique_lumas.append(piece_luma)
            if len(unique_bench) >= deploy_count:
                break

        # 若唯一棋子不足，补充剩余格子（允许重复）
        selected = list(unique_bench)
        if len(selected) < deploy_count:
            for idx in occupied_bench:
                if idx in selected:
                    continue
                selected.append(idx)
                if len(selected) >= deploy_count:
                    break

        # 4) 选择目标空位
        move_count = min(len(selected), len(empty_front), deploy_count)
        if move_count <= 0:
            return False

        selected = selected[:move_count]
        dest_front = empty_front[:move_count]

        logger.info(f'Deploy pieces: bench={selected} -> front={dest_front}')

        # 5) 拖动上阵
        for bench_idx, front_idx in zip(selected, dest_front):
            p1 = area_center(bench_slot_areas[bench_idx])
            p2 = area_center(front_slot_areas[front_idx])
            self.device.drag(p1, p2, name=f'CURRENCY_WAR_DEPLOY_{bench_idx + 1}_TO_{front_idx + 1}')
            self.device.sleep(0.6)

            # 等待目标格子不再匹配“空格子模板”，确认拖动生效后再进行下一步
            verify = Timer(3).start()
            while not verify.reached():
                self.device.screenshot()
                if not self.match_template_luma(front_empty_buttons[front_idx], similarity=0.8):
                    break
                self.device.sleep(0.2)
            else:
                logger.warning(f'Deploy verify timeout: front slot {front_idx + 1} still empty')

        return True
