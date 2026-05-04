from types import SimpleNamespace

import numpy as np
import pytest

from module.exception import GameNotRunningError, GamePageUnknownError
from module.ui.draggable_list import DraggableList
from module.config.config_generated import GeneratedConfig
from module.config.config_updater import ConfigUpdater
from module.config.deep import deep_get
from tasks.dungeon.keywords import KEYWORDS_DUNGEON_LIST
from tasks.forgotten_hall.challenge import DUNGEON_MODES, ForgottenHallChallenge
from tasks.forgotten_hall import stage_ocr
from tasks.forgotten_hall.challenge_modes.base import StandardDungeonMode
from tasks.forgotten_hall.keywords import ForgottenHallStage, KEYWORDS_FORGOTTEN_HALL_STAGE
from tasks.forgotten_hall.stage_ocr import ForgottenHallStageOcr, mark_locked_stage_buttons
from tasks.forgotten_hall.ui import ForgottenHallUI
from tasks.forgotten_hall.ui_parts import battle, preset_team, stage_selection
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


def test_select_preset_team_uses_requested_team_as_total_lower_bound():
    ui = object.__new__(ForgottenHallUI)
    calls = []
    ui.device = SimpleNamespace(screenshot=lambda: None)
    ui._get_preset_team_scroll_state = lambda: (True, 7, 0)
    ui._drag_preset_team_slider = lambda target_team, total_teams=None: calls.append(
        ('drag', target_team, total_teams)
    ) or True
    ui._get_preset_team_scroll_top_index = lambda total_teams: (True, 5, 1.0)
    ui._click_preset_team_slot = lambda slot_index: calls.append(('click', slot_index)) or True

    assert ui.select_preset_team(8) is True
    assert calls == [('drag', 5, 8), ('click', 2)]


def test_select_preset_team_retries_if_drag_stops_before_target_is_visible():
    ui = object.__new__(ForgottenHallUI)
    calls = []
    top_results = [4, 5]
    ui.device = SimpleNamespace(screenshot=lambda: None)
    ui._get_preset_team_scroll_state = lambda: (True, 7, 0)
    ui._drag_preset_team_slider = lambda target_team, total_teams=None: calls.append(
        ('drag', target_team, total_teams)
    ) or True
    ui._get_preset_team_scroll_top_index = lambda total_teams: (True, top_results.pop(0), 1.0)
    ui._click_preset_team_slot = lambda slot_index: calls.append(('click', slot_index)) or True

    assert ui.select_preset_team(8) is True
    assert calls == [('drag', 5, 8), ('drag', 5, 8), ('click', 2)]


def test_select_preset_team_does_not_click_if_target_remains_invisible_after_drag():
    ui = object.__new__(ForgottenHallUI)
    calls = []
    ui.device = SimpleNamespace(screenshot=lambda: None)
    ui._get_preset_team_scroll_state = lambda: (True, 7, 0)
    ui._drag_preset_team_slider = lambda target_team, total_teams=None: calls.append(
        ('drag', target_team, total_teams)
    ) or True
    ui._get_preset_team_scroll_top_index = lambda total_teams: (True, 4, 0.8)
    ui._click_preset_team_slot = lambda slot_index: calls.append(('click', slot_index)) or True

    assert ui.select_preset_team(8) is False
    assert calls == [('drag', 5, 8), ('drag', 5, 8)]


def test_configure_preset_teams_flow_fails_on_selection_failure():
    ui = object.__new__(ForgottenHallUI)
    selected = []
    ui._click_preset_team = lambda **kwargs: True
    ui.select_preset_team = lambda preset_index: selected.append(preset_index) or False
    ui._verify_team_selected_with_retry = lambda **kwargs: (_ for _ in ()).throw(
        AssertionError('verification should not run after selection failure')
    )

    assert ui._configure_preset_teams_flow(team1_preset=8, team2_preset=6, team_label='battle') is False
    assert selected == [8]


def test_stage_goto_propagates_preset_team_configuration_failure(monkeypatch):
    ui = object.__new__(ForgottenHallUI)
    ui.appear = lambda *args, **kwargs: True
    ui.stage_choose = lambda dungeon: True
    ui._click_preset_team = lambda timeout=15: True
    ui._configure_preset_teams = lambda team1_preset, team2_preset: False

    class FakeStageList:
        def select_row(self, stage_keyword, main):
            return True

    monkeypatch.setattr(stage_selection, 'STAGE_LIST', FakeStageList())

    assert ui.stage_goto(
        KEYWORDS_DUNGEON_LIST.Memory_of_Chaos,
        KEYWORDS_FORGOTTEN_HALL_STAGE.Stage_9,
        team1_preset=8,
        team2_preset=6,
    ) is False


def test_draggable_list_select_row_can_timeout_without_clicking():
    draggable_list = object.__new__(DraggableList)
    clicked = []
    main = SimpleNamespace(device=SimpleNamespace(click=lambda button: clicked.append(button)))

    assert draggable_list.select_row(
        row='Stage_9',
        main=main,
        insight=False,
        timeout=-1,
    ) is False
    assert clicked == []


def test_forgotten_hall_run_re_raises_game_not_running_without_delay():
    task = object.__new__(ForgottenHallChallenge)
    delays = []
    task.config = SimpleNamespace(task_delay=lambda **kwargs: delays.append(kwargs))

    def raise_game_not_running():
        raise GameNotRunningError('Game not running')

    task.ui_goto_main = raise_game_not_running

    with pytest.raises(GameNotRunningError):
        task.run()

    assert delays == []


def test_standard_mode_re_raises_scheduler_handled_errors():
    mode = StandardDungeonMode(
        dungeon_type='Memory_of_Chaos',
        max_stage=12,
        display_name='混沌回忆',
    )
    task = SimpleNamespace(
        goto_stage_selection_by_dungeon_type=lambda dungeon_type: True,
        check_and_claim_rewards=lambda skip_first_screenshot=False: False,
        detect_current_highest_stage=lambda max_stage, target_stars: (10, {10: 0}),
    )

    def raise_unknown_page(**kwargs):
        raise GamePageUnknownError

    task._challenge_stage = raise_unknown_page

    with pytest.raises(GamePageUnknownError):
        mode.run_auto_selection(
            task,
            team1_preset=8,
            team2_preset=6,
            team1_buff=0,
            team2_buff=0,
            target_stars=3,
            min_stage=1,
        )


def test_pure_fiction_failure_claims_rewards_and_retries_swapped_teams():
    mode = DUNGEON_MODES['Pure_Fiction']
    challenge_calls = []
    reward_calls = []

    task = SimpleNamespace(
        goto_stage_selection_by_dungeon_type=lambda dungeon_type: True,
        check_and_claim_rewards=lambda skip_first_screenshot=False: reward_calls.append(
            skip_first_screenshot
        ) or False,
        pure_fiction_next_stage_to_challenge=lambda: (4, {4: 0}),
    )

    def fake_challenge_stage(**kwargs):
        challenge_calls.append(kwargs)
        return (False, 0)

    task._challenge_stage = fake_challenge_stage

    assert mode.run_auto_selection(
        task,
        team1_preset=1,
        team2_preset=2,
        team1_buff=10,
        team2_buff=20,
        target_stars=3,
        min_stage=1,
    ) is False

    assert [
        (
            call['team1_preset'],
            call['team2_preset'],
            call['team1_buff'],
            call['team2_buff'],
        )
        for call in challenge_calls
    ] == [(1, 2, 10, 20), (2, 1, 20, 10)]
    assert reward_calls == [False, False, False]


def test_pure_fiction_swapped_team_success_claims_rewards_and_finishes():
    mode = DUNGEON_MODES['Pure_Fiction']
    challenge_results = [(False, 0), (True, 1)]
    challenge_calls = []
    reward_calls = []
    next_stage_results = [(4, {4: 0}), (-1, {4: 1})]

    task = SimpleNamespace(
        goto_stage_selection_by_dungeon_type=lambda dungeon_type: True,
        check_and_claim_rewards=lambda skip_first_screenshot=False: reward_calls.append(
            skip_first_screenshot
        ) or False,
        pure_fiction_next_stage_to_challenge=lambda: next_stage_results.pop(0),
    )

    def fake_challenge_stage(**kwargs):
        challenge_calls.append(kwargs)
        return challenge_results.pop(0)

    task._challenge_stage = fake_challenge_stage

    assert mode.run_auto_selection(
        task,
        team1_preset=1,
        team2_preset=2,
        team1_buff=10,
        team2_buff=20,
        target_stars=3,
        min_stage=1,
    ) is True

    assert [
        (
            call['team1_preset'],
            call['team2_preset'],
            call['team1_buff'],
            call['team2_buff'],
        )
        for call in challenge_calls
    ] == [(1, 2, 10, 20), (2, 1, 20, 10)]
    assert reward_calls == [False, False, False]


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


def test_ui_additional_confirms_quick_complete_popup():
    ui = object.__new__(ForgottenHallUI)
    clicked = []

    class FakeDevice:
        def click(self, button):
            clicked.append(button.name)

    ui.device = FakeDevice()
    ui.handle_reward = lambda: False
    ui.handle_battle_pass_notification = lambda: False
    ui.handle_monthly_card_reward = lambda: False
    ui.handle_get_light_cone = lambda: False
    ui.handle_ui_close = lambda button, interval=0: False
    ui.handle_ui_back = lambda button, interval=0: False
    ui.appear_then_click = lambda button, interval=0: False
    ui.handle_get_character = lambda: False
    ui.handle_forgotten_hall_buff = lambda: False

    def fake_appear(button, interval=0):
        return button.name == 'QUICK_COMPLETE_TITLE'

    ui.appear = fake_appear

    assert ui.ui_additional() is True
    assert clicked == ['QUICK_COMPLETE_CONFIRM']


def test_wait_for_pure_fiction_loaded_handles_delayed_start_story():
    ui = object.__new__(ForgottenHallUI)
    state = {'story_checks': 0}

    ui.device = SimpleNamespace(screenshot=lambda: None)
    ui.handle_forgotten_hall_buff = lambda: False

    class FakeNavigator:
        def handle_pure_fiction_start_story(self, device):
            state['story_checks'] += 1
            return state['story_checks'] == 2

    def fake_match_template_color(button, interval=0):
        return button.name == 'PURE_FICTION_ENTER_STORY' and state['story_checks'] >= 3

    ui.match_template_color = fake_match_template_color
    ui.appear = lambda button, interval=0: False

    assert ui._wait_for_pure_fiction_loaded(
        timeout=1.0,
        navigator=FakeNavigator(),
        ready_stability=0,
    ) is True
    assert state['story_checks'] == 3


def test_goto_pure_fiction_handles_start_story_before_ui_ensure():
    ui = object.__new__(ForgottenHallUI)
    ui.device = SimpleNamespace(screenshot=lambda: None)
    handled = []

    ui.handle_forgotten_hall_buff = lambda interval=0: False
    ui._pure_fiction_stage_selection_ready = lambda interval=0: False
    ui._new_treasures_lightward_navigator = lambda: object()
    ui._handle_pure_fiction_start_story = lambda navigator=None: handled.append(navigator) or True
    ui._wait_for_pure_fiction_loaded = lambda **kwargs: True
    ui.ui_ensure = lambda page: (_ for _ in ()).throw(
        AssertionError('should not leave the Pure Fiction start story page')
    )

    assert ui.goto_stage_selection_by_dungeon_type('Pure_Fiction') is True
    assert handled


def test_goto_pure_fiction_fails_when_stage_selection_not_confirmed():
    ui = object.__new__(ForgottenHallUI)
    ui.device = SimpleNamespace(screenshot=lambda: None)

    class FakeNavigator:
        def goto_pure_fiction_from_guide(self, device):
            return True

    ui.handle_forgotten_hall_buff = lambda interval=0: False
    ui._pure_fiction_stage_selection_ready = lambda interval=0: False
    ui._handle_pure_fiction_start_story = lambda navigator=None: False
    ui._new_treasures_lightward_navigator = lambda: FakeNavigator()
    ui.ui_ensure = lambda page: None
    ui._wait_for_pure_fiction_loaded = lambda **kwargs: False

    assert ui.goto_stage_selection_by_dungeon_type('Pure_Fiction') is False


def test_enter_pure_fiction_team_selection_clicks_team_button_despite_icon_false_positive():
    ui = object.__new__(ForgottenHallUI)
    clicked = []
    state = {'team_button_clicked': False}

    def click(button):
        clicked.append(button.name)
        if button.name == 'PURE_FICTION_TEAM_BUTTON':
            state['team_button_clicked'] = True

    ui.device = SimpleNamespace(screenshot=lambda: None, click=click)
    ui.handle_forgotten_hall_buff = lambda: False

    def fake_match_template_color(button, interval=0):
        return button.name == 'PURE_FICTION_ENTER_STORY' and not state['team_button_clicked']

    def fake_appear(button, interval=0, similarity=None):
        if button.name in {'PURE_FICTION_PRESET_ICON', 'PURE_FICTION_CLEAR_ICON'}:
            return True
        if button.name == 'PURE_FICTION_TEAM_TITLE':
            return state['team_button_clicked']
        if button.name == 'PURE_FICTION_TEAM_BUTTON':
            return not state['team_button_clicked']
        return False

    ui.match_template_color = fake_match_template_color
    ui.appear = fake_appear

    assert ui._enter_pure_fiction_team_selection(timeout=1.0) is True
    assert clicked == ['PURE_FICTION_TEAM_BUTTON']


def test_pure_fiction_stage_goto_defaults_empty_buffs_to_option_one():
    ui = object.__new__(ForgottenHallUI)
    configured_buffs = []

    ui.goto_stage_selection_by_dungeon_type = lambda dungeon_type: True
    ui.pure_fiction_resolve_stage_num = lambda stage_id: stage_id
    ui.pure_fiction_select_stage = lambda stage_num: True
    ui._configure_pure_fiction_preset_teams = lambda team1_preset, team2_preset: True
    ui._configure_pure_fiction_buffs = lambda team1_buff, team2_buff: (
        configured_buffs.append((team1_buff, team2_buff)) or True
    )

    assert ui.stage_goto_by_dungeon_type(
        'Pure_Fiction',
        KEYWORDS_FORGOTTEN_HALL_STAGE.Stage_4,
        team1_preset=1,
        team2_preset=2,
        team1_buff=0,
        team2_buff=None,
    ) is True
    assert configured_buffs == [(1, 1)]


def test_preset_team_scroll_estimates_eight_total_from_bottom_thumb():
    ui = object.__new__(preset_team.ForgottenHallPresetTeamMixin)
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    x1, _, x2, _ = ui.PRESET_TEAM_SCROLLBAR_ROI
    image[469:666, x1:x2] = 255
    ui.device = SimpleNamespace(image=image)

    valid, total, top = ui._get_preset_team_scroll_state()

    assert valid is True
    assert total == 8
    assert top == 5


def test_auto_engage_dismisses_click_blank_prompt_before_moving(monkeypatch):
    ui = object.__new__(ForgottenHallUI)
    calls = []

    class FakeDevice:
        image = np.zeros((720, 1280, 3), dtype=np.uint8)

        def screenshot(self):
            calls.append('screenshot')

    class FakeJoystick:
        def __init__(self, main):
            self.main = main

        def __enter__(self):
            calls.append('joystick_enter')
            return self

        def __exit__(self, exc_type, exc, tb):
            calls.append('joystick_exit')

        def set(self, direction=0, run=True):
            calls.append(('move', direction, run))

    prompt_open = {'value': True}
    ui.device = FakeDevice()
    ui._handle_forgotten_hall_click_blank_prompt = lambda interval=0.8: (
        prompt_open.update(value=False) or calls.append('prompt') or True
        if prompt_open['value'] else False
    )
    ui.is_combat_executing = lambda: not prompt_open['value']
    ui.handle_map_run_2x = lambda: calls.append('run_2x')
    ui.aim = SimpleNamespace(predict=lambda *args, **kwargs: None, aimed_enemy=None)
    ui.handle_map_A = lambda: calls.append('attack')
    ui.combat_poor_try = lambda: []

    monkeypatch.setattr(battle, 'JoystickContact', FakeJoystick)

    assert ui.auto_engage_enemy(move_duration=1, timeout=1) is True
    assert calls.index('prompt') < calls.index('joystick_enter')
    assert ('move', 0, True) not in calls
    assert 'run_2x' not in calls


def test_auto_engage_clears_possible_intro_prompt_before_joystick(monkeypatch):
    ui = object.__new__(ForgottenHallUI)
    calls = []
    moved = {'value': False}

    class FakeDevice:
        image = np.zeros((720, 1280, 3), dtype=np.uint8)

        def screenshot(self):
            calls.append('screenshot')

        def click(self, button):
            calls.append(('click', button.name))

    class FakeJoystick:
        def __init__(self, main):
            self.main = main

        def __enter__(self):
            calls.append('joystick_enter')
            return self

        def __exit__(self, exc_type, exc, tb):
            calls.append('joystick_exit')

        def set(self, direction=0, run=True):
            moved['value'] = True
            calls.append(('move', direction, run))

    ui.device = FakeDevice()
    ui._handle_forgotten_hall_click_blank_prompt = lambda interval=0.8: False
    ui.is_combat_executing = lambda: moved['value']
    ui.handle_map_run_2x = lambda: calls.append('run_2x')
    ui.aim = SimpleNamespace(predict=lambda *args, **kwargs: None, aimed_enemy=None)
    ui.handle_map_A = lambda: calls.append('attack')
    ui.combat_poor_try = lambda: []

    monkeypatch.setattr(battle, 'JoystickContact', FakeJoystick)

    assert ui.auto_engage_enemy(move_duration=1, timeout=1) is True
    assert calls.index(('click', 'FORGOTTEN_HALL_POSSIBLE_INTRO_PROMPT')) < calls.index(
        'joystick_enter'
    )
    assert calls.index('joystick_enter') < calls.index(('move', 0, True))


def test_auto_engage_restarts_movement_after_stationary_prompt(monkeypatch):
    ui = object.__new__(ForgottenHallUI)
    calls = []

    class FakeDevice:
        image = np.zeros((720, 1280, 3), dtype=np.uint8)

        def screenshot(self):
            calls.append('screenshot')

    class FakeJoystick:
        def __init__(self, main):
            self.main = main

        def __enter__(self):
            calls.append('joystick_enter')
            return self

        def __exit__(self, exc_type, exc, tb):
            calls.append('joystick_exit')

        def set(self, direction=0, run=True):
            calls.append(('move', direction, run))

    class FakeTimer:
        move_instances = 0

        def __init__(self, limit, count=0):
            self.limit = limit
            self.calls = 0
            if limit == 8:
                FakeTimer.move_instances += 1
                self.move_instance = FakeTimer.move_instances
            else:
                self.move_instance = 0

        def start(self):
            return self

        def reached(self):
            self.calls += 1
            if self.limit == 8:
                if self.move_instance == 1:
                    return True
                return self.calls > 2
            if self.limit == 15:
                return False
            if self.limit == 0.5:
                return True
            if self.limit == 0.3:
                return False
            return False

        def reset(self):
            self.calls = 0
            return self

    prompt_open = {'value': True}
    moved = {'value': False}
    ui.device = FakeDevice()
    ui._handle_forgotten_hall_click_blank_prompt = lambda interval=0.8: (
        prompt_open.update(value=False) or calls.append('prompt') or True
        if prompt_open['value'] else False
    )
    ui.is_combat_executing = lambda: moved['value']
    ui.handle_map_run_2x = lambda: calls.append('run_2x')
    ui.aim = SimpleNamespace(predict=lambda *args, **kwargs: None, aimed_enemy=None)
    ui.handle_map_A = lambda: calls.append('attack')
    ui.combat_poor_try = lambda: []
    ui._prepare_auto_engage_after_map_enter = lambda skip_first_screenshot=True: skip_first_screenshot

    def set_moved(direction=0, run=True):
        moved['value'] = True
        calls.append(('move', direction, run))

    monkeypatch.setattr(battle, 'JoystickContact', FakeJoystick)
    monkeypatch.setattr(battle, 'Timer', FakeTimer)
    FakeJoystick.set = lambda self, direction=0, run=True: set_moved(direction, run)

    assert ui.auto_engage_enemy(move_duration=8, timeout=15) is True
    assert calls.index('prompt') < calls.index(('move', 0, True))
    assert calls.count('joystick_enter') == 2


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
    assert task._get_pure_fiction_buff_config('EmptyText', default=1) == 1
    assert task._get_pure_fiction_buff_config('Missing', default=1) == 1


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
