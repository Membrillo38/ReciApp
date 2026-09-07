# Cooking Mode Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ReciApp cooking mode a complete, tactile, animated step-by-step experience based on `/Users/andrescasillas/Downloads/file.mp4`, preserving the existing white visual treatment.

**Architecture:** Keep the feature local to `RecipeDetailView.swift`: `CookingView` owns navigation/completion state, `CookingStepCard` owns visual state, and small private controls provide reusable motion and haptics. Use SwiftUI-native state, `ScrollViewReader`, explicit transitions, and UIKit feedback generators without adding dependencies.

**Tech Stack:** SwiftUI, UIKit haptics, iOS 17+, Xcode Simulator.

**Spec:** `/Users/andrescasillas/Downloads/file.mp4` sampled at 5 fps; observed pattern is a white/light cooking surface with stacked step cards, one highlighted active card, a floating recipe image, and a bottom action bar with Help, Bite, and Ingredients.

## Global Constraints

- Preserve the existing white/light ReciApp theme and avoid Liquid Glass.
- Keep the existing `Cook` entry point, `Help`, `Bite`, `Ingredients`, close action, accessibility labels, and ingredient data.
- Add only scoped cooking-mode behavior; do not alter recipe persistence, auth, onboarding, or backend behavior.
- Respect `accessibilityReduceMotion` by reducing animation intensity and duration.
- Haptics stay subtle and only fire for meaningful actions: selecting, advancing, opening a secondary surface, and completing the recipe.

### Task 1: Complete cooking-mode state and navigation

**Files:**
- Modify: `IosAPP/ReciApp/Views/RecipeDetailView.swift:617-750`

**Interfaces:**
- `CookingView` owns `selectedStepIndex`, completed step orders, completion feedback, and sheet/alert presentation.
- Existing `CookingStepCard`, `CookingControlButton`, and `CookingIngredientsSheet` remain the local component boundary.

- [ ] Add guarded step selection, animated scroll-to-selection, previous-step behavior, next-step behavior, and final-step completion behavior.
- [ ] Mark the current step complete when advancing, expose progress in the header/action bar, and provide a non-empty empty state when a recipe has no steps.
- [ ] Keep Help and Ingredients actions connected to their existing presentations and keep close dismissible.

### Task 2: Add the video-inspired motion and tactile feedback

**Files:**
- Modify: `IosAPP/ReciApp/Views/RecipeDetailView.swift:1-850`

**Interfaces:**
- Add a private haptic helper in the same file so no project-file membership change is needed.
- Add `accessibilityReduceMotion` environment reads to the cooking surface/components.

- [ ] Animate cooking entry, staggered step-card appearance, active-card selection, completion marks, thumbnail changes, progress, and bottom controls.
- [ ] Give each step a restrained alternating resting rotation and animate the selected step back to neutral.
- [ ] Add subtle pressed-state scale feedback to cooking controls and haptics for selection, navigation, secondary actions, and completion.
- [ ] Keep text readable, cards tappable, and accessibility values descriptive.

### Task 3: Build and runtime-verify the cooking flow

**Files:**
- Verify: `IosAPP/ReciApp/Views/RecipeDetailView.swift`

- [ ] Build `ReciApp` for the booted iOS Simulator.
- [ ] Launch the design preview, open Weeknight, open a recipe, and enter cooking mode.
- [ ] Verify the initial cards, rotated inactive steps, active step, bottom controls, step advancement, ingredient sheet, Help action, and final completion state using accessibility plus a screenshot.

## Self-review

- The 5-fps video pattern is covered by stacked cards, highlighted active step, floating image, and bottom action bar.
- The requested rotation, animations, haptics, and functional step progression each have an explicit implementation task.
- No unrelated app systems or external dependencies are included.
