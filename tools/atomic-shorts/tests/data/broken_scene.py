# ruff: noqa: F403, F405  (Manim scenes use its documented star import)
from manim import *


class StoryboardScene(Scene):
    def construct(self):
        lattice = VGroup(*[Dot(point=[x, 0, 0]) for x in range(3)])
        self.play(ShowCreation(lattice), run_time=1)
