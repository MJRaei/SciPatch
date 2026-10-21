# ruff: noqa: F403, F405  (Manim scenes use its documented star import)
from manim import *


class StoryboardScene(Scene):
    def construct(self):
        title = Text("Rock salt", font_size=40)
        lattice = VGroup(
            *[
                Dot(point=[x, y, 0], color=BLUE_E if (x + y) % 2 else YELLOW_B)
                for x in range(-2, 3)
                for y in range(-2, 3)
            ]
        )
        self.play(Write(title), run_time=1)
        self.play(title.animate.to_edge(UP), FadeIn(lattice), run_time=1)
        self.wait(1)
