"""
Flow3rTron

(c) 2023 Jonas Jelten <jj@sft.lol>
(c) 2023 Leo Fahrbach <leo@sft.lol>
"""

from st3m.application import Application, ApplicationContext
from st3m.ui.view import BaseView, ViewManager
from st3m.input import InputController, InputState
from ctx import Context
import st3m.run

import io
import math
import sys
import time

from st3m import logging

log = logging.Log(__name__, level=logging.INFO)


def chain(iters):
    for i in iters:
        yield from i


def chainva(*iters):
    yield from chain(iters)


def collides(a, b):
    """
    check if two lines collide
    a: ((start_x, y), (end_x, y))
    """
    p1 = a[0]
    p2 = a[1]
    p3 = b[0]
    p4 = b[1]

    denominator_a = ((p4[0] - p3[0]) * (p1[1] - p3[1])) - (
        (p4[1] - p3[1]) * (p1[0] - p3[0])
    )
    denominator_b = ((p2[0] - p1[0]) * (p1[1] - p3[1])) - (
        (p2[1] - p1[1]) * (p1[0] - p3[0])
    )
    numerator = (p4[1] - p3[1]) * (p2[0] - p1[0]) - (p4[0] - p3[0]) * (p2[1] - p1[1])

    if math.isclose(numerator, 0) and math.isclose(denominator_a, 0):
        # coincident
        return True

    if math.isclose(numerator, 0):
        # parallel
        return False

    u_a = denominator_a / numerator
    u_b = denominator_b / numerator
    return 0 < u_a < 1 and 0 < u_b < 1


class Player:
    def __init__(self, start_pos):
        self._pos = start_pos
        self._color = (255, 255, 0)

        # in degrees
        self._direction = 0

        # pixel per second
        self._speed = 60

        # list of (wendepunkt_x, y)
        self._traces = [start_pos]

        # lol
        self._dead = False

    def get_traces(self):
        last = self._traces[0]
        for trace in chainva(self._traces[1:], [self._pos]):
            yield (last, trace)
            last = trace

    def check_collision(self, all_traces):
        if self._dead:
            return

        my_latest_trace = (self._traces[-1], self._pos)
        for trace in all_traces:
            if trace == my_latest_trace:
                continue
            if collides(my_latest_trace, trace):
                self.die()

    def draw(self, ctx: Context) -> None:
        player_size = 10

        ctx.rgb(*self._color)
        ctx.move_to(*self._traces[0])

        for trace in chainva(self._traces[1:], [self._pos]):
            ctx.line_to(*trace)

        ctx.stroke()

        if self._dead:
            ctx.rgb(255, 0, 0)

        ctx.rectangle(
            self._pos[0] - player_size / 2,
            self._pos[1] - player_size / 2,
            player_size,
            player_size,
        ).fill()

    def set_speed(self, speed):
        # illegal speed
        if speed < 0:
            return
        self._speed = speed

    def set_direction(self, direction):
        if (direction - self._direction) % 360 == 180:
            return

        if direction != self._direction:
            self._direction = direction
            self._traces.append(self._pos)

    def die(self):
        self._dead = True

    def is_dead(self):
        return self._dead

    def move(self, delta_ms):
        if self._dead:
            return

        # Update the location of the player based on its speed and direction
        dir_rad = (self._direction * math.tau) / 360
        speed_ms = self._speed * delta_ms / 1000
        self._pos = (
            self._pos[0] + speed_ms * math.sin(dir_rad),
            self._pos[1] - speed_ms * math.cos(dir_rad),
        )

        if (self._pos[0] ** 2) + (self._pos[1] ** 2) > (120**2):
            self.die()


class Board:
    dimx = 240
    dimy = 240

    def __init__(self):
        # player_id -> player
        self.players = dict()
        self.players[0] = Player(start_pos=(-50, 0))

        self.local_player = 0

    def draw(self, ctx: Context) -> None:
        for player in self.players.values():
            player.draw(ctx)

    def think(self, inc: InputController, delta_ms: int):
        # True: 10 directions
        # False: 5 directions, the upper petals only
        all_petals = False

        # TODO: process network infos, apply to players

        # process local input
        stepsize = 1 if all_petals else 2
        for i in range(0, 10, stepsize):
            petal = inc.captouch.petals[i]
            # TODO: speed adjustments
            # (rad, phi) = petal.position

            # take the first petal for now :)
            if petal.whole.pressed:
                self.players[self.local_player].set_direction(i * 360 / 10)
                break

        # move players
        for p in self.players.values():
            p.move(delta_ms)

        # check collisions
        for p in self.players.values():
            p.check_collision(chain(pl.get_traces() for pl in self.players.values()))

    def game_over(self) -> bool:
        return all(p.is_dead() for p in self.players.values())


class TronGame:
    def __init__(self) -> None:
        log.info("Game started")
        self._board = Board()
        self._done = False

        self._start_time = time.time_ns()
        self._duration = 0

    def is_done(self):
        return self._done

    def draw(self, ctx: Context) -> None:
        # black background, clear buffer.
        ctx.rgb(0, 0, 0).rectangle(-120, -120, 240, 240).fill()
        self._board.draw(ctx)

        if self._done:
            ctx.rgba(0, 0, 0, 220).rectangle(-100, 30, 200, 60)
            ctx.text_align = ctx.CENTER
            ctx.text_baseline = ctx.MIDDLE
            ctx.font_size = 20
            ctx.rgba(255, 255, 255, 200).move_to(0, 0).text(f"{self._duration:.03f}s")

    def think(self, inc: InputController, delta_ms: int) -> None:
        self._board.think(inc, delta_ms)

        if self._board.game_over():
            if not self._done:
                self._done = True
                self._duration = (time.time_ns() - self._start_time) / 1e9
                log.info(f"Game over: {self._duration}s")


class GameView(BaseView):
    def __init__(self) -> None:
        super().__init__()
        self._input = InputController()
        self._game = TronGame()

    def on_enter(self, vm: ViewManager | None) -> None:
        super().on_enter(vm)

    def draw(self, ctx: Context) -> None:
        if self._game:
            self._game.draw(ctx)

    def think(self, ins: InputState, delta_ms: int) -> None:
        super().think(ins, delta_ms)
        self._input.think(ins, delta_ms)
        self._game.think(self._input, delta_ms)

        if self._game.is_done():
            if self._input.buttons.app.right.pressed:
                self._game = TronGame()

            # TODO: start next game via some menu


class Flow3rTron(Application):
    def __init__(self, app_ctx: ApplicationContext) -> None:
        super().__init__(app_ctx)

    def on_enter(self, vm: ViewManager | None) -> None:
        super().on_enter(vm)

        if self.vm is None:
            raise RuntimeError("vm is None")

        log.info("Flow3rTron launching!")

        # switch to game view directly
        self.vm.replace(GameView())

    def draw(self, ctx: Context) -> None:
        # TODO: menu
        pass

    def think(self, ins: InputState, delta_ms: int) -> None:
        super().think(ins, delta_ms)

        # TODO: navigation


if __name__ == "__main__":
    # run with mptremote run flow3rtron/__init__.py
    st3m.run.run_view(Flow3rTron(ApplicationContext()))
