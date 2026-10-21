---
name: atomic-shorts
description: >-
  Short narrated science explainer videos (AtomicShorts). check_storyboard
  checks a storyboard's JSON, narration time per scene against a target length,
  and lists scientific terms to fact-check; render_scene renders Manim
  Community animation code to MP4 and returns Manim's error and line when it
  fails; narrate adds a text-to-speech narration track and extends the video to
  fit. Use to communicate results to students, the public, or colleagues.
---

## Recipes

1. Write the storyboard JSON: {"prompt", "title", "age_level", "video_length",
   "scenes": [{"scene_id", "title", "narration", "visuals": [{"description"}]}]}.
2. `check_storyboard(file, target_seconds=[30, 60])`; shorten or lengthen the
   narration until `length` is "fits"; verify every term in `terms_to_fact_check`.
3. Write one Manim scene (`class StoryboardScene(Scene)`, `from manim import *`)
   whose animation times follow each scene's `narration_seconds`; 2D primitives
   (Dot, Circle, Square, Line, Arrow, VGroup, Text, MathTex) render fastest.
4. `render_scene(file)` at low quality; on an error, fix the reported line and
   retry; render at "medium" or "high" for the final cut.
5. `narrate(video, storyboard=file)`.

## Pitfalls

- Use Create for shapes and Write for text; ShowCreation no longer exists.
- Guard self.play against empty animation lists.
- Narration needs the internet (Google text-to-speech).
