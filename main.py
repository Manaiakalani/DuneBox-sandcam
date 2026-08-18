"""
AR Sandbox POC

Controls
--------
Left-drag   raise terrain (simulator only)
Right-drag  lower terrain (simulator only)
Scroll      resize brush  (simulator only)
C           toggle contour lines
G           toggle creatures
V           cycle creature set (modern / prehistoric / all / none)
O           toggle volcano placement mode (click to place & erupt)
K           trigger earthquake at centre (testing)
S           toggle sound mute
N           toggle day/night cycle
E           toggle ecosystem simulation
+/-         speed up / slow down day/night cycle
P           pause / resume day/night cycle
F5          save current terrain snapshot
R           reset terrain (simulator only)
B           toggle DuneBox bridge (TCP link to C++ app)
U           toggle WebSocket depth server (remote monitoring)
Tab         open / close settings sidebar
Esc / Q     quit
"""

import logging
import sys
import time

import numpy as np
import pygame

from diagnostics import show_startup_diagnostics

from ai_guide import (
    AsyncConnectionTester,
    GuideEngine,
    ProviderConfig,
    TemplateNarrator,
    build_async_narrator,
)
from creatures import CreatureManager, MARKER_DINO_SPAWN, MARKER_EXTINCTION
from day_night import DayNightCycle
from ecosystem import EcosystemManager
# from depth_source import MouseSimulator
from sensor_api import create_sensor
from dem_loader import save_terrain_snapshot
from interaction_engine import InteractionEngine
from renderer import Renderer
from game_modes import GameManager
from sounds import SoundManager
from ui import Config, Sidebar, draw_guide_overlay
from webcam_observer import (
    AsyncCameraDiscovery,
    AsyncCameraTester,
    CalibrationData,
    WebcamObserver,
)
from bridge import AppBridge
from depth_server import DepthStreamServer
from volcano import (
    MARKER_VOLCANO_PLACE,
    MARKER_VOLCANO_TRIGGER,
    VolcanoManager,
)
from earthquake import EarthquakeDetector

logger = logging.getLogger(__name__)

FPS           = 60
BRUSH_MIN     = 8
BRUSH_MAX     = 180
BRUSH_DEFAULT = 50
BRUSH_DELTA   = 0.012
MAX_RENDER_W  = 960
MAX_RENDER_H  = 720


def _draw_startup_screen(
    screen: pygame.Surface,
    *,
    title: str,
    message: str,
    progress: float,
) -> None:
    progress = max(0.0, min(1.0, progress))
    screen.fill((14, 18, 26))

    title_font = pygame.font.SysFont("segoeui", 30, bold=True)
    body_font = pygame.font.SysFont("segoeui", 18)
    small_font = pygame.font.SysFont("segoeui", 14)

    panel_w = min(520, screen.get_width() - 80)
    panel_h = 170
    panel = pygame.Rect(
        (screen.get_width() - panel_w) // 2,
        (screen.get_height() - panel_h) // 2,
        panel_w,
        panel_h,
    )

    card = pygame.Surface(panel.size, pygame.SRCALPHA)
    pygame.draw.rect(card, (22, 28, 40, 238), card.get_rect(), border_radius=16)
    pygame.draw.rect(card, (72, 124, 188), card.get_rect(), width=2, border_radius=16)
    screen.blit(card, panel.topleft)

    screen.blit(title_font.render(title, True, (220, 228, 238)), (panel.x + 20, panel.y + 18))
    screen.blit(body_font.render(message, True, (170, 182, 198)), (panel.x + 20, panel.y + 66))

    track = pygame.Rect(panel.x + 20, panel.y + 110, panel_w - 40, 12)
    fill = pygame.Rect(track.x, track.y, int(track.width * progress), track.height)
    pygame.draw.rect(screen, (44, 52, 72), track, border_radius=6)
    if fill.width > 0:
        pygame.draw.rect(screen, (60, 130, 210), fill, border_radius=6)

    percent = small_font.render(f"{int(progress * 100):d}%", True, (120, 132, 150))
    screen.blit(percent, (track.right - percent.get_width(), track.bottom + 10))
    pygame.display.flip()


def _pump_startup_events() -> bool:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            return False
    return True


def _prewarm_creatures(screen: pygame.Surface) -> bool:
    stages = 2
    current_stage = 0
    cancelled = False

    def _progress(stage_label: str, index: int, total: int, _scale: float) -> bool:
        nonlocal cancelled
        if not _pump_startup_events():
            cancelled = True
            return False
        fraction = (current_stage + (index / max(1, total))) / stages
        _draw_startup_screen(
            screen,
            title="Loading Sandbox",
            message=f"Preparing {stage_label.lower()} sprites...",
            progress=fraction,
        )
        return True

    _draw_startup_screen(
        screen,
        title="Loading Sandbox",
        message="Preparing creature sprites...",
        progress=0.0,
    )
    if not _pump_startup_events():
        return False

    current_stage = 0
    if CreatureManager.prewarm_assets(progress=_progress) is False:
        return False

    current_stage = 1
    _draw_startup_screen(
        screen,
        title="Loading Sandbox",
        message="Creature sprites are ready.",
        progress=1.0,
    )
    return not cancelled


def _fallback_display_bounds() -> list[tuple[int, int, int, int]]:
    x = 0
    bounds: list[tuple[int, int, int, int]] = []
    for w, h in pygame.display.get_desktop_sizes():
        bounds.append((x, 0, w, h))
        x += w
    return bounds


def _get_display_bounds() -> list[tuple[int, int, int, int]]:
    desktops = pygame.display.get_desktop_sizes()
    if sys.platform != "win32":
        return _fallback_display_bounds()

    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        bounds: list[tuple[int, int, int, int]] = []
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HMONITOR,
            wintypes.HDC,
            ctypes.POINTER(RECT),
            wintypes.LPARAM,
        )

        def _callback(_monitor, _hdc, rect_ptr, _lparam):
            rect = rect_ptr.contents
            bounds.append(
                (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
            )
            return True

        ctypes.windll.user32.EnumDisplayMonitors(
            0, 0, callback_type(_callback), 0
        )
        if len(bounds) == len(desktops):
            return bounds
    except Exception:
        pass

    return _fallback_display_bounds()


def _move_window_to_display(
    screen: pygame.Surface,
    display_bounds: tuple[int, int, int, int],
    *,
    borderless: bool,
) -> None:
    if sys.platform != "win32":
        return

    info = pygame.display.get_wm_info()
    hwnd = info.get("window")
    if not hwnd:
        return

    import ctypes
    from ctypes import wintypes

    left, top, display_w, display_h = display_bounds
    win_w, win_h = screen.get_size()
    if not borderless:
        left += max(0, (display_w - win_w) // 2)
        top += max(0, (display_h - win_h) // 2)

    flags = 0x0004 | 0x0010 | 0x0040 | 0x0020  # no z-order, no activate, show, refresh frame
    ctypes.windll.user32.SetWindowPos(
        wintypes.HWND(hwnd),
        wintypes.HWND(0),
        int(left),
        int(top),
        int(win_w),
        int(win_h),
        flags,
    )


def _make_display(config: Config) -> tuple[pygame.Surface, int, int]:
    """Create (or recreate) the pygame display surface from current config."""
    displays = _get_display_bounds()
    idx = min(config.display_index, len(displays) - 1)
    left, top, dw, dh = displays[idx]

    if config.fullscreen:
        # Borderless windowed fullscreen is more reliable than exclusive
        # fullscreen on Windows/projector setups.
        if sys.platform == "win32":
            screen = pygame.display.set_mode((dw, dh), pygame.NOFRAME)
        else:
            screen = pygame.display.set_mode((dw, dh), pygame.NOFRAME, display=idx)
        _move_window_to_display(screen, (left, top, dw, dh), borderless=True)
        w, h = screen.get_size()
    else:
        w, h = config.windowed_w, config.windowed_h
        screen = pygame.display.set_mode((w, h))
        _move_window_to_display(screen, (left, top, dw, dh), borderless=False)
    return screen, w, h


def _compute_render_size(display_w: int, display_h: int) -> tuple[int, int]:
    scale = min(1.0, min(MAX_RENDER_W / display_w, MAX_RENDER_H / display_h))
    render_w = max(320, int(display_w * scale))
    render_h = max(240, int(display_h * scale))
    return render_w, render_h


def _screen_to_scene(
    x: int, y: int, screen_w: int, screen_h: int, scene_w: int, scene_h: int
) -> tuple[int, int]:
    sx = int(x * scene_w / max(1, screen_w))
    sy = int(y * scene_h / max(1, screen_h))
    return sx, sy


def _make_guide(config: Config) -> GuideEngine | None:
    if not config.ai_enabled:
        return None

    backend = config.llm_backend if config.llm_enabled else "template"
    provider_config = ProviderConfig(
        backend=backend,
        base_url=config.llm_base_url,
        model=config.llm_model,
        timeout_seconds=config.llm_timeout_seconds,
    )
    return GuideEngine(
        template_narrator=TemplateNarrator(),
        async_narrator=build_async_narrator(provider_config),
        event_cooldown=config.guide_update_seconds,
    )


def _make_calibration(config: Config) -> CalibrationData:
    points = config.vision_calibration_points or []
    if len(points) != 4:
        return CalibrationData()
    return CalibrationData(camera_points=tuple((float(x), float(y)) for x, y in points))


def main() -> int:
    extended_diag = "--diagnostics" in sys.argv

    pygame.init()
    pygame.display.set_caption("AR Sandbox")

    config  = Config.load()
    screen, screen_w, screen_h = _make_display(config)

    # ── startup diagnostics ───────────────────────────────────────────
    if not show_startup_diagnostics(
        screen,
        extended=extended_diag,
        probe_webcam=extended_diag or config.vision_enabled,
        camera_index=config.camera_index,
    ):
        pygame.quit()
        return 0

    if not _prewarm_creatures(screen):
        pygame.quit()
        return 0
    render_w, render_h = _compute_render_size(screen_w, screen_h)
    scene = pygame.Surface((render_w, render_h))

    # source  = MouseSimulator(render_w, render_h)
    source   = create_sensor(
        {
            "sensor_type": config.sensor_type,
            "sensor_fallback": config.sensor_fallback,
        },
        width=render_w,
        height=render_h,
        min_depth_mm=config.min_depth_mm,
        max_depth_mm=config.max_depth_mm,
        temporal_alpha=config.temporal_alpha,
        change_threshold_mm=config.change_threshold_mm,
        persistence_frames=config.persistence_frames,
        foreground_reject_mm=config.foreground_reject_mm,
    )
    renderer = Renderer(render_w, render_h)
    creatures = CreatureManager(
        n_sharks=config.shark_count,
        n_dinos=config.dinosaur_count,
    )
    guide = _make_guide(config)
    vision = WebcamObserver(config.camera_index) if config.vision_enabled else None
    calibration = _make_calibration(config)
    interactions = InteractionEngine()
    camera_discovery = AsyncCameraDiscovery()
    camera_tester = AsyncCameraTester()
    llm_tester = AsyncConnectionTester()
    sidebar  = Sidebar()
    sound_mgr = SoundManager(enabled=config.sound_enabled)
    sound_mgr.set_master_volume(config.sound_master_volume)
    day_night = DayNightCycle(cycle_duration=120.0)
    day_night_enabled = True
    prev_day_night_phase = ""
    game_mgr = GameManager()
    app_bridge = AppBridge(host="127.0.0.1", port=9876, role="server")
    app_bridge.start()
    bridge_enabled = True
    depth_server = DepthStreamServer(
        host=config.depth_server_host,
        port=config.depth_server_port,
        max_fps=config.depth_server_max_fps,
    )
    depth_server_enabled = config.depth_server_enabled
    if depth_server_enabled:
        depth_server.start()
    volcano_mgr = VolcanoManager(render_w, render_h)
    volcano_place_mode = False  # 'O' key toggles placement mode
    earthquake_det = EarthquakeDetector(render_w, render_h)
    eco_mgr = EcosystemManager(render_w, render_h)
    eco_enabled = False
    app_start_time = time.monotonic()
    debug_font = pygame.font.SysFont(None, 18)
    hud_font = pygame.font.SysFont(None, 22)
    clock    = pygame.time.Clock()

    brush_radius = BRUSH_DEFAULT

    # Status flash overlay (shows brief messages like "Ecosystem ON", calibration results, etc.)
    status_flash_timer = 0.0  # seconds remaining to show message
    status_flash_text = ""

    try:
        running = True
        while running:
            dt = clock.tick(FPS) / 1000.0

            # ── events ────────────────────────────────────────────────────────
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    continue

                # Sidebar gets first look at every event
                consumed = sidebar.handle_event(event, config)
                if consumed:
                    continue

                if event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_ESCAPE, pygame.K_q):
                        if game_mgr.is_active() and event.key == pygame.K_ESCAPE:
                            game_mgr.end_game()
                        else:
                            running = False
                    elif event.key == pygame.K_F1:
                        game_mgr.start_game("dam", source.get_frame())
                    elif event.key == pygame.K_F2:
                        game_mgr.start_game("volcano", source.get_frame())
                    elif event.key == pygame.K_F3:
                        game_mgr.start_game("watershed", source.get_frame())
                    elif event.key == pygame.K_F4:
                        game_mgr.start_game("biome", source.get_frame())
                    elif event.key == pygame.K_TAB:
                        sidebar.toggle()
                    elif event.key == pygame.K_r:
                        if hasattr(source, "reset"):
                            source.reset()
                    elif event.key == pygame.K_c:
                        config.show_contours = not config.show_contours
                        config.request_save()
                    elif event.key == pygame.K_g:
                        config.show_creatures = not config.show_creatures
                        config.request_save()
                    elif event.key == pygame.K_v:
                        new_set = creatures.cycle_creature_set()
                        status_flash_text = f"Creatures: {new_set}"
                        status_flash_timer = 1.5
                    elif event.key == pygame.K_s:
                        muted = sound_mgr.toggle_mute()
                        config.sound_enabled = not muted
                        config.request_save()
                    elif event.key == pygame.K_F5:
                        try:
                            saved = save_terrain_snapshot(source.get_frame())
                            status_flash_text = f"Saved: {saved.name}"
                        except Exception as exc:
                            status_flash_text = f"Save failed: {exc}"
                        status_flash_timer = 2.5
                    elif event.key == pygame.K_b:
                        bridge_enabled = not bridge_enabled
                        if bridge_enabled:
                            app_bridge.start()
                        else:
                            app_bridge.stop()
                    elif event.key == pygame.K_n:
                        day_night_enabled = not day_night_enabled
                        if not day_night_enabled:
                            prev_day_night_phase = ""
                    elif event.key == pygame.K_e:
                        eco_enabled = not eco_enabled
                        eco_mgr.set_enabled(eco_enabled)
                        status_flash_text = f"Ecosystem {'ON' if eco_enabled else 'OFF'}"
                        status_flash_timer = 2.0
                    elif event.key == pygame.K_EQUALS or event.key == pygame.K_PLUS:
                        day_night.adjust_speed(+0.5)
                    elif event.key == pygame.K_MINUS:
                        day_night.adjust_speed(-0.5)
                    elif event.key == pygame.K_p:
                        day_night.toggle_pause()
                    elif event.key == pygame.K_u:
                        depth_server_enabled = not depth_server_enabled
                        config.depth_server_enabled = depth_server_enabled
                        if depth_server_enabled:
                            depth_server.start()
                        else:
                            depth_server.stop()
                        config.request_save()
                    elif event.key == pygame.K_o:
                        volcano_place_mode = not volcano_place_mode
                        status_flash_text = (
                            "Volcano placement ON (click to place)"
                            if volcano_place_mode else "Volcano placement OFF"
                        )
                        status_flash_timer = 2.0
                    elif event.key == pygame.K_k:
                        earthquake_det.force_trigger(render_w // 2, render_h // 2)
                        status_flash_text = "Earthquake triggered!"
                        status_flash_timer = 2.0
                    elif event.key == pygame.K_a:
                        if hasattr(source, "auto_calibrate_flat_surface"):
                            result = source.auto_calibrate_flat_surface()
                            if result:
                                config.min_depth_mm, config.max_depth_mm = result
                                config.depth_range_changed = True
                                config.request_save()
                                status_flash_text = (
                                    f"Depth calibrated: {result[0]}-{result[1]} mm"
                                )
                            else:
                                status_flash_text = "Calibration failed: no valid depth"
                        else:
                            status_flash_text = "Auto-calibration not supported"
                        status_flash_timer = 2.5
                elif event.type == pygame.MOUSEBUTTONDOWN and volcano_place_mode:
                    if event.button == 1:
                        vx, vy = _screen_to_scene(
                            event.pos[0], event.pos[1],
                            screen.get_width(), screen.get_height(),
                            render_w, render_h,
                        )
                        idx = volcano_mgr.place_volcano(vx, vy)
                        volcano_mgr.trigger_eruption(idx)
                        volcano_place_mode = False
                        status_flash_text = f"Volcano placed at ({vx}, {vy})"
                        status_flash_timer = 2.0
                elif event.type == pygame.MOUSEWHEEL:
                    brush_radius = max(BRUSH_MIN, min(BRUSH_MAX,
                                                      brush_radius + event.y * 4))

            # ── react to config changes ───────────────────────────────────────
            if config.display_changed:
                config.display_changed = False
                screen, screen_w, screen_h = _make_display(config)
                render_w, render_h = _compute_render_size(screen_w, screen_h)
                scene = pygame.Surface((render_w, render_h))
                renderer = Renderer(render_w, render_h)
                source.resize(render_w, render_h)
                volcano_mgr.resize(render_w, render_h)
                earthquake_det.resize(render_w, render_h)
                eco_mgr = EcosystemManager(render_w, render_h)
                eco_mgr.set_enabled(eco_enabled)

            if config.depth_range_changed:
                config.depth_range_changed = False
                if hasattr(source, "set_depth_range"):
                    source.set_depth_range(config.min_depth_mm, config.max_depth_mm)

            if config.filter_changed:
                config.filter_changed = False
                if hasattr(source, "set_filter_params"):
                    source.set_filter_params(
                        temporal_alpha=config.temporal_alpha,
                        change_threshold_mm=config.change_threshold_mm,
                        persistence_frames=config.persistence_frames,
                        foreground_reject_mm=config.foreground_reject_mm,
                    )

            if config.ai_changed:
                config.ai_changed = False
                if guide is not None:
                    guide.close()
                guide = _make_guide(config)

            if config.vision_changed:
                config.vision_changed = False
                if vision is not None:
                    vision.close()
                    vision = None
                calibration = _make_calibration(config)
                if config.vision_enabled:
                    vision = WebcamObserver(config.camera_index)
                    if vision.error_message:
                        config.camera_test_status = "error"
                        config.camera_test_message = vision.error_message
                    elif not config.camera_test_message:
                        config.camera_test_status = "ok"
                        config.camera_test_message = f"Camera {config.camera_index} ready."
                else:
                    config.available_cameras = []
                    config.camera_scan_status = "idle"
                    config.camera_scan_message = ""
                    config.camera_test_status = "idle"
                    config.camera_test_message = ""
                    config.calibration_message = ""

            if config.llm_test_requested:
                config.llm_test_requested = False
                backend = config.llm_backend if config.llm_enabled else "template"
                provider_config = ProviderConfig(
                    backend=backend,
                    base_url=config.llm_base_url,
                    model=config.llm_model,
                    timeout_seconds=config.llm_timeout_seconds,
                )
                started = llm_tester.start(provider_config)
                if not started and config.llm_test_status == "running":
                    config.llm_test_message = "A connection test is already running."

            if config.camera_test_requested:
                config.camera_test_requested = False
                started = camera_tester.start(config.camera_index)
                if not started and config.camera_test_status == "running":
                    config.camera_test_message = "A camera test is already running."

            if config.camera_scan_requested:
                config.camera_scan_requested = False
                started = camera_discovery.start()
                if not started and config.camera_scan_status == "scanning":
                    config.camera_scan_message = "A camera scan is already running."

            llm_test_result = llm_tester.poll()
            if llm_test_result is not None:
                config.llm_test_status = "ok" if llm_test_result.ok else "error"
                config.llm_test_message = llm_test_result.summary

            camera_test_result = camera_tester.poll()
            if camera_test_result is not None:
                config.camera_test_status = "ok" if camera_test_result.ok else "error"
                config.camera_test_message = camera_test_result.summary

            camera_scan_result = camera_discovery.poll()
            if camera_scan_result is not None:
                config.available_cameras = [
                    {
                        "index": camera.index,
                        "label": camera.summary.replace(" is working at ", "  "),
                    }
                    for camera in camera_scan_result
                ]
                if config.available_cameras:
                    config.camera_scan_status = "ok"
                    config.camera_scan_message = (
                        f"Found {len(config.available_cameras)} camera(s). Select one below."
                    )
                    available_indexes = {int(camera["index"]) for camera in config.available_cameras}
                    if config.camera_index not in available_indexes:
                        config.camera_index = int(config.available_cameras[0]["index"])
                        config.vision_changed = True
                else:
                    config.camera_scan_status = "error"
                    config.camera_scan_message = "No working cameras were detected."

            if config.save_requested:
                config.save_requested = False
                config.save()

            creatures.set_targets(
                sharks=config.shark_count,
                dinosaurs=config.dinosaur_count,
            )

            # ── sculpt (simulator only) ───────────────────────────────────────
            buttons = pygame.mouse.get_pressed()
            mx, my  = pygame.mouse.get_pos()
            scene_mx, scene_my = _screen_to_scene(
                mx, my, screen.get_width(), screen.get_height(), render_w, render_h
            )
            scene_brush_radius = max(
                1,
                int(round(brush_radius * min(render_w / screen.get_width(), render_h / screen.get_height()))),
            )
            if buttons[0]:
                source.sculpt(scene_mx, scene_my, scene_brush_radius, +BRUSH_DELTA)
            elif buttons[2]:
                source.sculpt(scene_mx, scene_my, scene_brush_radius, -BRUSH_DELTA)

            # ── render ────────────────────────────────────────────────────────
            frame = source.get_frame()

            # Day/night cycle
            light_tint = None
            if day_night_enabled:
                day_night.update(dt)
                phase = day_night.get_phase()
                light_tint = day_night.get_terrain_tint()

                # Creature night mode
                creatures.set_night_mode(phase == "night")

                # Sound phase
                sound_mgr.set_day_night_phase(phase)

                # Dawn bird chirp one-shot
                if phase != prev_day_night_phase:
                    if phase == "dawn":
                        sound_mgr.play_event("dawn_birds")
                    prev_day_night_phase = phase
            else:
                creatures.set_night_mode(False)
                sound_mgr.set_day_night_phase("day")

            sound_mgr.update(frame, dt)
            if config.show_creatures:
                creatures.update(frame, dt)
                for snd_event in creatures.pop_sound_events():
                    sound_mgr.play_event(snd_event)

            # ── ecosystem simulation ──────────────────────────────────────
            if eco_enabled:
                eco_mgr.set_day_phase(
                    day_night.get_phase() in ("day", "dawn") if day_night_enabled else True
                )
                eco_mgr.update(frame, dt)
                # Feed vegetation map to creature system for food-seeking
                if config.show_creatures:
                    creatures.set_vegetation_map(eco_mgr.get_vegetation_map())
                    for hx, hy in creatures.get_herbivore_positions():
                        eco_mgr.graze_at(hx, hy)
            else:
                creatures.set_vegetation_map(None)

            renderer.draw(scene, frame,
                          show_contours=config.show_contours,
                          colour_scheme=config.colour_scheme,
                          light_tint=light_tint)

            # Sky effects (stars, moon, sun) — after terrain, before creatures
            if day_night_enabled:
                day_night.draw_sky_effects(scene, frame)

            # Vegetation overlay — between terrain and creatures
            if eco_enabled:
                eco_mgr.draw(scene)

            if config.show_creatures:
                creatures.draw(scene, frame)

            # ── volcano system ────────────────────────────────────────────────
            volcano_mgr.update(frame, dt)
            volcano_mgr.draw(scene)
            for v_snd in volcano_mgr.pop_sound_events():
                sound_mgr.play_event(v_snd)

            # ── earthquake system ─────────────────────────────────────────────
            quake_triggered = earthquake_det.update(frame, dt=dt)
            if quake_triggered:
                epi = earthquake_det.get_epicenter()
                if epi is not None:
                    if config.show_creatures:
                        creatures.trigger_stampede(epi[0], epi[1])
                    volcano_mgr.trigger_nearby(epi[0], epi[1], radius=150, chance=0.7)
            for eq_snd in earthquake_det.pop_sound_events():
                sound_mgr.play_event(eq_snd)
            earthquake_det.draw(scene)

            # ── game modes ────────────────────────────────────────────────────
            game_mgr.update(frame, dt)
            game_mgr.draw(scene)
            if game_mgr.pop_started():
                sound_mgr.play_event("marker_detected")
            if game_mgr.pop_ended():
                sound_mgr.play_event("creature_despawn")

            vision_events = []
            vision_objects = []
            if config.vision_enabled and vision is not None:
                if config.vision_calibrating:
                    new_calibration = vision.auto_calibrate()
                    if new_calibration is not None:
                        calibration = new_calibration
                        config.vision_calibration_points = [
                            [float(x), float(y)] for x, y in new_calibration.camera_points
                        ]
                        config.vision_calibrating = False
                        config.calibration_message = "Calibration updated from corner markers."
                        config.request_save()
                    elif not config.calibration_message:
                        config.calibration_message = (
                            "Show corner tags 100, 101, 102, and 103 to calibrate the sandbox."
                        )
                vision_objects = vision.get_objects(calibration, (render_w, render_h), frame=frame)
                interactions.update(
                    vision_objects,
                    frame,
                    time.monotonic(),
                    reactions_enabled=config.object_reactions_enabled,
                )
                if config.vision_calibrating or config.vision_debug_enabled:
                    overlay_rgb = vision.get_warped_rgb(calibration, (render_w, render_h))
                    overlay_label = "Calibration View"
                    overlay_alpha = 92 if config.vision_calibrating else 64
                    if overlay_rgb is None:
                        overlay_rgb = vision.get_preview_rgb((render_w, render_h))
                        overlay_label = "Camera Preview"
                        overlay_alpha = 72 if config.vision_calibrating else 56
                    if overlay_rgb is not None:
                        overlay_surface = pygame.surfarray.make_surface(overlay_rgb.swapaxes(0, 1))
                        overlay_surface.set_alpha(overlay_alpha)
                        scene.blit(overlay_surface, (0, 0))
                        label = debug_font.render(overlay_label, True, (255, 230, 90))
                        shadow = debug_font.render(overlay_label, True, (0, 0, 0))
                        scene.blit(shadow, (11, 11))
                        scene.blit(label, (10, 10))
                interactions.draw(scene)
                if config.vision_debug_enabled:
                    for kind, _camera_pos, mapped_pos in vision.debug_points(calibration, (render_w, render_h)):
                        px, py = int(mapped_pos[0]), int(mapped_pos[1])
                        pygame.draw.circle(scene, (255, 230, 90), (px, py), 9, 2)
                        tag = debug_font.render(kind, True, (255, 230, 90))
                        scene.blit(tag, (px + 8, py - 8))
                vision_events = interactions.pop_events()
                for _ve in vision_events:
                    sound_mgr.play_event("marker_detected")

                # ArUco markers for dinosaur spawning (IDs 10-13)
                for obj in vision_objects:
                    mid = obj.marker_id
                    if mid in MARKER_DINO_SPAWN or mid == MARKER_EXTINCTION:
                        dino_events = creatures.handle_marker(mid, obj.sandbox_pos, frame)
                        for de in dino_events:
                            sound_mgr.play_event(de)

                # ArUco markers for volcano (IDs 20, 21, 13)
                for obj in vision_objects:
                    mid = obj.marker_id
                    if mid in (MARKER_VOLCANO_PLACE, MARKER_VOLCANO_TRIGGER):
                        volcano_mgr.handle_marker(mid, obj.sandbox_pos)
                    elif mid == MARKER_EXTINCTION:
                        volcano_mgr.handle_marker(mid, obj.sandbox_pos)

            new_eruptions = volcano_mgr.pop_new_eruptions()

            # ── bridge: send detected markers, handle incoming ────────────
            if bridge_enabled and app_bridge.is_connected():
                for obj in vision_objects:
                    if hasattr(obj, "marker_id") and hasattr(obj, "sandbox_pos"):
                        app_bridge.send({
                            "type": "marker_detected",
                            "marker_id": obj.marker_id,
                            "position": list(obj.sandbox_pos),
                            "timestamp": time.time(),
                        })
                for vx, vy in new_eruptions:
                    app_bridge.send({
                        "type": "volcano_eruption",
                        "x": vx / max(1, render_w),
                        "y": vy / max(1, render_h),
                    })
                for bmsg in app_bridge.poll():
                    btype = bmsg.get("type", "")
                    if btype == "theme_change":
                        new_scheme = bmsg.get("theme", "")
                        if new_scheme in ("terrain", "heat", "greyscale", "desert"):
                            config.colour_scheme = new_scheme
                    elif btype == "water_status":
                        pass  # could display as HUD overlay

            # ── depth server: push frame + state to WebSocket clients ─────
            if depth_server_enabled:
                depth_server.push_frame(frame)
                creature_counts = creatures.counts() if config.show_creatures else {"sharks": 0, "dinosaurs": 0}
                _game_info = game_mgr.get_status()
                depth_server.push_state({
                    "fps": round(clock.get_fps(), 1),
                    "creatures": {
                        "total": sum(creature_counts.values()),
                        **creature_counts,
                    },
                    "theme": config.colour_scheme,
                    "water_enabled": config.show_contours,
                    "water_coverage": float(np.mean(frame < 0.38)) if frame is not None else 0.0,
                    "lava_active": volcano_mgr.is_erupting(),
                    "sound_muted": not config.sound_enabled,
                    "day_night": {
                        "enabled": day_night_enabled,
                        "phase": day_night.get_phase() if day_night_enabled else "",
                        "time": round(day_night.get_time_of_day(), 3) if day_night_enabled else 0.0,
                    },
                    "game": _game_info,
                    "sensor": {
                        "type": source.get_sensor_name(),
                        "connected": True,
                    },
                    "clients": depth_server.get_client_count(),
                    "uptime": round(time.monotonic() - app_start_time, 1),
                })

                # ── process dashboard commands ────────────────────────
                for cmd in depth_server.poll_commands():
                    action = cmd.get("action", "")
                    value = cmd.get("value")
                    if action == "set_theme":
                        if value in ("terrain", "heat", "greyscale", "desert"):
                            config.colour_scheme = value
                            config.request_save()
                    elif action == "toggle_water":
                        config.show_contours = not config.show_contours
                        config.request_save()
                    elif action == "toggle_lava":
                        pass  # lava not yet implemented as a toggle
                    elif action == "toggle_sound":
                        muted = sound_mgr.toggle_mute()
                        config.sound_enabled = not muted
                        config.request_save()
                    elif action == "toggle_day_night":
                        day_night_enabled = not day_night_enabled
                        if not day_night_enabled:
                            prev_day_night_phase = ""
                    elif action == "cycle_speed":
                        if value == "up":
                            day_night.adjust_speed(+0.5)
                        elif value == "down":
                            day_night.adjust_speed(-0.5)
                    elif action == "start_game":
                        if value in GameManager.get_available_modes():
                            game_mgr.start_game(value, source.get_frame())

            guide_message = None
            active_challenge = None
            if guide is not None:
                counts = creatures.counts() if config.show_creatures else {"sharks": 0, "dinosaurs": 0}
                guide_message = guide.update(
                    frame,
                    time.monotonic(),
                    shark_count=counts["sharks"],
                    dinosaur_count=counts["dinosaurs"],
                    creatures_enabled=config.show_creatures,
                    guide_enabled=config.guide_enabled,
                    challenges_enabled=config.guide_challenges_enabled,
                    verbosity=config.guide_verbosity,
                )
                active_challenge = guide.active_challenge
                if config.guide_enabled:
                    for vision_event in vision_events:
                        pushed = guide.push_external_event(
                            event_key=vision_event.event_key,
                            title=vision_event.title,
                            body=vision_event.body,
                            now=time.monotonic(),
                            verbosity=config.guide_verbosity,
                        )
                        if pushed is not None:
                            guide_message = pushed
            else:
                vision_events.clear()

            # Screen shake offset from volcano eruptions + earthquake
            v_shake_dx, v_shake_dy = volcano_mgr.get_shake_offset()
            eq_shake_dx, eq_shake_dy = earthquake_det.get_shake_offset()
            shake_dx = v_shake_dx + eq_shake_dx
            shake_dy = v_shake_dy + eq_shake_dy

            if scene.get_size() == screen.get_size():
                screen.blit(scene, (shake_dx, shake_dy))
            else:
                scaled = pygame.transform.scale(scene, screen.get_size())
                screen.blit(scaled, (shake_dx, shake_dy))

            draw_guide_overlay(
                screen,
                config,
                title=guide_message.title if guide_message else None,
                body=guide_message.body if guide_message else None,
                challenge_text=(
                    active_challenge.prompt
                    if (active_challenge is not None and config.guide_challenges_enabled)
                    else None
                ),
                challenge_done=bool(guide_message.completed) if guide_message else False,
            )

            pygame.draw.circle(screen, (255, 255, 255), (mx, my), brush_radius, 1)

            # ── DEM flash notification ────────────────────────────────────
            if status_flash_timer > 0:
                status_flash_timer -= dt
                flash_alpha = min(255, int(255 * min(1.0, status_flash_timer / 0.3)))
                flash_surf = hud_font.render(status_flash_text, True, (255, 230, 90))
                flash_surf.set_alpha(flash_alpha)
                screen.blit(
                    flash_surf,
                    (screen.get_width() // 2 - flash_surf.get_width() // 2, 30),
                )

            creatures_state = "on" if config.show_creatures else "off"
            creature_set_label = creatures.creature_set
            sound_state = "off" if not config.sound_enabled else "on"
            ai_state = "ai:on" if config.ai_enabled else "ai:off"
            dn_state = f"cycle:{day_night.get_phase()}" if day_night_enabled else "cycle:off"
            bridge_state = (
                "bridge:connected" if (bridge_enabled and app_bridge.is_connected())
                else "bridge:on" if bridge_enabled
                else "bridge:off"
            )
            ds_clients = depth_server.get_client_count()
            depth_state = (
                f"ws:{ds_clients}cl" if depth_server_enabled and ds_clients > 0
                else "ws:on" if depth_server_enabled
                else "ws:off"
            )
            game_hud = "  F1-F4 games" if not game_mgr.is_active() else "  Esc end game"
            volcano_state = "erupting" if volcano_mgr.is_erupting() else f"{volcano_mgr.count()}v"
            eco_state = "eco:on" if eco_enabled else "eco:off"
            hud = (f"Tab settings  C contours  G creatures:{creatures_state}  V set:{creature_set_label}  "
                   f"E {eco_state}  O volcano:{volcano_state}  "
                   f"S sound:{sound_state}  N {dn_state}  B {bridge_state}  U {depth_state}  R reset  "
                   f"brush {brush_radius}px  |  {config.colour_scheme}  {ai_state}{game_hud}")
            label = hud_font.render(hud, True, (200, 200, 200))
            screen.blit(label, (10, screen.get_height() - 24))

            # Day/night phase indicator (upper-right)
            if day_night_enabled:
                day_night.draw_phase_hud(
                    screen, hud_font,
                    screen.get_width() - 140, 10,
                )

            # Ecosystem stats and biome tooltip
            if eco_enabled:
                eco_mgr.draw_stats(
                    screen, debug_font,
                    10, screen.get_height() - 44,
                    herbivore_count=creatures.get_herbivore_count() if config.show_creatures else 0,
                    carnivore_count=creatures.get_carnivore_count() if config.show_creatures else 0,
                )
                eco_scene_mx, eco_scene_my = _screen_to_scene(
                    mx, my, screen.get_width(), screen.get_height(), render_w, render_h,
                )
                eco_mgr.draw_biome_tooltip(screen, debug_font, eco_scene_mx, eco_scene_my)

            sidebar.update(dt)
            sidebar.draw(screen, config)

            pygame.display.flip()
    finally:
        try:
            config.save()
        except Exception:
            logger.exception("Failed to save config during shutdown")
        try:
            if guide is not None:
                guide.close()
        except Exception:
            logger.exception("Failed to close AI guide during shutdown")
        try:
            camera_discovery.close()
        except Exception:
            logger.exception("Failed to close camera discovery during shutdown")
        try:
            camera_tester.close()
        except Exception:
            logger.exception("Failed to close camera tester during shutdown")
        try:
            if vision is not None:
                vision.close()
        except Exception:
            logger.exception("Failed to close vision system during shutdown")
        try:
            sound_mgr.cleanup()
        except Exception:
            logger.exception("Failed to cleanup sound manager during shutdown")
        try:
            llm_tester.close()
        except Exception:
            logger.exception("Failed to close LLM tester during shutdown")
        try:
            app_bridge.stop()
        except Exception:
            logger.exception("Failed to stop app bridge during shutdown")
        try:
            depth_server.stop()
        except Exception:
            logger.exception("Failed to stop depth server during shutdown")
        try:
            if hasattr(source, "close"):
                source.close()
        except Exception:
            logger.exception("Failed to close depth source during shutdown")
        finally:
            pygame.quit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
