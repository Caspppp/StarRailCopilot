from types import SimpleNamespace

import numpy as np

from module.config.config_generated import GeneratedConfig
from module.config.config_updater import ConfigUpdater
from module.config.deep import deep_get
from tasks.forgotten_hall.challenge import DUNGEON_MODES, ForgottenHallChallenge
from tasks.forgotten_hall import stage_ocr
from tasks.forgotten_hall.keywords import ForgottenHallStage, KEYWORDS_FORGOTTEN_HALL_STAGE
from tasks.forgotten_hall.stage_ocr import ForgottenHallStageOcr, mark_locked_stage_buttons
from tasks.forgotten_hall.ui import ForgottenHallUI
from tasks.forgotten_hall.ui_parts import stage_selection
from tools.forgotten_hall_star_detector.star_detector import (
    cluster_stars_by_proximity,
    detect_yellow_stars,
    match_stars_to_stages,
)


def test_star_detector_matches_yellow_star_cluster_to_stage():
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    for x in (80, 100, 120):
        image[350:358, x:x + 8] = (254, 199, 112)

    star_regions = detect_yellow_stars(image, search_area=(0, 281, 1280, 581))
    clusters = cluster_stars_by_proximity(star_regions)
    stage_star_map = match_stars_to_stages(clusters, [(90, 300, 110, 330)])

    assert len(star_regions) == 3
    assert len(clusters) == 1
    assert stage_star_map[0] == 3


def test_find_starting_stage_prefers_highest_unfinished_unlocked_stage():
    ui = object.__new__(ForgottenHallUI)

    assert ui.find_starting_stage({1: 3, 2: 2, 3: -1}, target_stars=3, max_stage=3) == 2
    assert ui.find_starting_stage({1: 3, 2: 3, 3: 3}, target_stars=3, max_stage=3) == -1
    assert ui.find_starting_stage({1: 0, 2: -1, 3: -1}, target_stars=3, max_stage=3) == 1


def test_forgotten_hall_preset_team_defaults_are_distinct():
    assert GeneratedConfig.ForgottenHallChallenge_Team1Preset == 1
    assert GeneratedConfig.ForgottenHallChallenge_Team2Preset == 2


def test_forgotten_hall_preset_team_normalization_keeps_teams_distinct():
    data = {
        'ForgottenHallChallenge': {
            'ForgottenHallChallenge': {
                'Team1Preset': 1,
                'Team2Preset': 1,
            }
        }
    }

    changed = ConfigUpdater.normalize_forgotten_hall_preset_teams(data)

    assert changed == ['ForgottenHallChallenge.ForgottenHallChallenge.Team2Preset']
    assert deep_get(data, 'ForgottenHallChallenge.ForgottenHallChallenge.Team1Preset') == 1
    assert deep_get(data, 'ForgottenHallChallenge.ForgottenHallChallenge.Team2Preset') == 2

    data['ForgottenHallChallenge']['ForgottenHallChallenge']['Team1Preset'] = 2
    data['ForgottenHallChallenge']['ForgottenHallChallenge']['Team2Preset'] = 2

    ConfigUpdater.normalize_forgotten_hall_preset_teams(data)

    assert deep_get(data, 'ForgottenHallChallenge.ForgottenHallChallenge.Team1Preset') == 2
    assert deep_get(data, 'ForgottenHallChallenge.ForgottenHallChallenge.Team2Preset') == 1


def _stage_button(stage_num, area, star_count=0, is_locked=False):
    return SimpleNamespace(
        area=area,
        matched_keyword=getattr(KEYWORDS_FORGOTTEN_HALL_STAGE, f'Stage_{stage_num}'),
        star_count=star_count,
        is_locked=is_locked,
    )


def test_mark_locked_stage_buttons_uses_final_button_areas(monkeypatch):
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    buttons = [
        _stage_button(7, (275, 444, 334, 519), is_locked=True),
        _stage_button(8, (439, 302, 529, 378), is_locked=True),
        _stage_button(9, (692, 357, 781, 433), is_locked=True),
        _stage_button(10, (850, 357, 929, 430), is_locked=True),
    ]
    seen = []

    def fake_detect_unlocked_text(image, search_area, ocr_model=None, save_debug=False, debug_index=0):
        seen.append((search_area, debug_index))
        return debug_index == 10

    monkeypatch.setattr(stage_ocr, 'detect_unlocked_text', fake_detect_unlocked_text)

    locked_stage_ids = mark_locked_stage_buttons(image, buttons, ocr_model=object())

    assert locked_stage_ids == [10]
    assert [button.is_locked for button in buttons] == [False, False, False, True]
    assert seen[-1] == ((849, 430, 929, 450), 10)


def test_detect_current_highest_stage_skips_locked_visible_stage(monkeypatch):
    ui = object.__new__(ForgottenHallUI)
    ui.device = SimpleNamespace(screenshot=lambda: None)
    buttons = [
        _stage_button(7, (275, 444, 334, 519), is_locked=False),
        _stage_button(8, (439, 302, 529, 378), is_locked=False),
        _stage_button(9, (692, 357, 781, 433), is_locked=False),
        _stage_button(10, (850, 357, 929, 430), is_locked=True),
    ]

    class FakeStageList:
        cur_buttons = buttons

        def load_rows(self, main):
            return None

    monkeypatch.setattr(stage_selection, 'STAGE_LIST', FakeStageList())

    current_stage, stage_stars = ui.detect_current_highest_stage(max_stage=10, target_stars=3)

    assert current_stage == 9
    assert stage_stars == {7: 0, 8: 0, 9: 0, 10: -1}


def test_locked_stage_marking_survives_filtered_ocr_noise(monkeypatch):
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    ocr = object.__new__(ForgottenHallStageOcr)
    ocr.name = 'OCR_STAGE'
    boxes = [
        (275, 444, 334, 519),
        (439, 302, 529, 378),
        (586, 261, 631, 318),
        (692, 357, 781, 433),
        (850, 357, 929, 430),
    ]

    monkeypatch.setattr(ocr, '_find_number', lambda image: boxes)
    monkeypatch.setattr(
        ocr,
        'ocr_multi_lines',
        lambda image_list: [('07', 0.99), ('08', 0.99), ('大', 0.90), ('09', 0.99), ('10', 0.99)],
    )

    from tools.forgotten_hall_star_detector import star_detector
    from module.ocr import models

    monkeypatch.setattr(star_detector, 'detect_yellow_stars', lambda image: [])
    monkeypatch.setattr(star_detector, 'cluster_stars_by_proximity', lambda star_regions: [])
    monkeypatch.setattr(star_detector, 'match_stars_to_stages', lambda star_clusters, boxes: {})
    monkeypatch.setattr(models, 'TextSystem', lambda lang: object())
    monkeypatch.setattr(
        stage_ocr,
        'detect_unlocked_text',
        lambda image, search_area, ocr_model=None, save_debug=False, debug_index=0: debug_index == 10,
    )

    buttons = ocr.matched_ocr(image, ForgottenHallStage)

    assert [button.matched_keyword.id for button in buttons] == [7, 8, 9, 10]
    assert {button.matched_keyword.id: button.is_locked for button in buttons} == {
        7: False,
        8: False,
        9: False,
        10: True,
    }


def test_handle_battle_success_confirms_quick_complete_before_returning():
    ui = object.__new__(ForgottenHallUI)
    clicked = []
    quick_popup_open = {'value': True}

    class FakeDevice:
        def screenshot(self):
            return None

        def click(self, button):
            clicked.append(button.name)
            quick_popup_open['value'] = False

    ui.device = FakeDevice()

    def fake_appear(button, interval=0):
        if button.name == 'QUICK_COMPLETE_TITLE':
            return quick_popup_open['value']
        if button.name == 'FORGOTTEN_HALL_CHECK':
            return True
        return False

    ui.appear = fake_appear
    ui.match_template_color = lambda button, interval=0: False
    ui.appear_then_click = lambda button, interval=0: False
    ui.handle_reward = lambda interval=0: False
    ui.handle_popup_confirm = lambda: False
    ui.handle_popup_single = lambda: False

    assert ui.handle_battle_success() is True
    assert clicked == ['QUICK_COMPLETE_CONFIRM']


def test_check_and_claim_rewards_waits_for_reward_page_before_returning():
    ui = object.__new__(ForgottenHallUI)
    clicked = []

    class FakeDevice:
        state = 'stage'

        def screenshot(self):
            if self.state == 'opening':
                self.state = 'still_stage'
            elif self.state == 'still_stage':
                self.state = 'reward_claim'
            elif self.state == 'reward_claim_clicked':
                self.state = 'reward_exit'
            elif self.state == 'exit_clicked':
                self.state = 'stage_returned'

        def click(self, button):
            clicked.append(button.name)
            if button.name == 'REWARD_INDICATOR':
                self.state = 'opening'
            elif button.name == 'REWARD_CLAIM_BUTTON':
                self.state = 'reward_claim_clicked'
            elif button.name == 'REWARD_EXIT':
                self.state = 'exit_clicked'

    device = FakeDevice()
    ui.device = device

    def fake_appear(button, interval=0):
        if button.name == 'REWARD_INDICATOR':
            return device.state == 'stage'
        if button.name == 'REWARD_CLAIM_BUTTON':
            return device.state == 'reward_claim'
        if button.name == 'REWARD_EXIT':
            return device.state == 'reward_exit'
        if button.name == 'FORGOTTEN_HALL_CHECK':
            return device.state in {'stage', 'still_stage', 'stage_returned'}
        return False

    ui.appear = fake_appear
    ui.handle_reward = lambda interval=0: False
    ui.handle_popup_confirm = lambda: False
    ui.handle_popup_single = lambda: False

    assert ui.check_and_claim_rewards() is True
    assert clicked == ['REWARD_INDICATOR', 'REWARD_CLAIM_BUTTON', 'REWARD_EXIT']


def test_challenge_config_dungeon_types_filters_unknown_and_falls_back():
    task = object.__new__(ForgottenHallChallenge)
    task.config = SimpleNamespace(
        ForgottenHallChallenge_DungeonTypes=['Memory_of_Chaos', 'Unknown_Mode'],
        ForgottenHallChallenge_DungeonType='Pure_Fiction',
    )

    assert task._get_selected_dungeon_types() == ['Memory_of_Chaos']

    task.config = SimpleNamespace(
        ForgottenHallChallenge_DungeonTypes=[],
        ForgottenHallChallenge_DungeonType='Apocalyptic_Shadow',
    )

    assert task._get_selected_dungeon_types() == ['Apocalyptic_Shadow']


def test_challenge_buff_config_keeps_existing_value_semantics():
    task = object.__new__(ForgottenHallChallenge)
    task.config = SimpleNamespace(
        Numeric=2,
        DigitText='3',
        KeywordText='击破',
        KeywordList=['击破', '', '忆灵'],
        EmptyText='',
    )

    assert task._get_buff_config('Numeric') == 2
    assert task._get_buff_config('DigitText') == 3
    assert task._get_buff_config('KeywordText') == '击破'
    assert task._get_buff_config('KeywordList') == ['击破', '忆灵']
    assert task._get_buff_config('EmptyText') == 0
    assert task._get_buff_config('Missing', default=1) == 1


def test_dungeon_modes_expose_required_mode_interface():
    expected = {'Memory_of_Chaos', 'Pure_Fiction', 'Apocalyptic_Shadow'}

    assert expected.issubset(DUNGEON_MODES)
    for dungeon_type in expected:
        mode = DUNGEON_MODES[dungeon_type]
        assert mode.dungeon_type == dungeon_type
        assert isinstance(mode.max_stage, int)
        assert mode.display_name
        assert callable(mode.run_auto_selection)
        assert callable(mode.get_stage_star_count)


def test_ui_facade_keeps_split_methods_available_from_public_class():
    assert ForgottenHallUI.stage_goto.__module__.endswith('.stage_selection')
    assert ForgottenHallUI.pure_fiction_select_stage.__module__.endswith('.pure_fiction')
    assert ForgottenHallUI._click_preset_team.__module__.endswith('.preset_team')
    assert ForgottenHallUI.auto_engage_enemy.__module__.endswith('.battle')
    assert ForgottenHallUI.check_and_claim_rewards.__module__.endswith('.reward')
