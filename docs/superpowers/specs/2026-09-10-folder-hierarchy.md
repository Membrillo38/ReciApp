# Folder Hierarchy Specification

## Goal

Extend ReciApp's existing local recipe organization with arbitrary-depth folders while preserving every existing recipe and folder assignment.

## Required behavior

- Create, rename, recolor, reparent, and delete folders and subfolders.
- Keep folder names globally unique, trimmed, non-empty, and at most 20 characters.
- Reject self-parenting and any move that would create a cycle.
- Store recipes in any folder depth. A recipe belongs to exactly one folder or `Uncategorized`.
- Let users move one or several recipes through an accessible menu and drag one recipe onto a folder.
- Keep child folders visible inside their parent and allow recursive navigation.
- Persist hierarchy, recipe assignments, ordering, and independent folder/recipe grid-or-list preferences per account.
- Decode the existing v3 flat folder cache and migrate every folder to the root without changing assignments.
- Keep server recipes authoritative. Folder metadata remains local and requires no network mutation.
- Empty-folder deletion remains immediate. Deleting a non-empty folder requires confirmation and a destination; child folders survive by moving to the deleted folder's parent.
- Show loading, empty, validation, and failure states without discarding the last valid local snapshot.

## Verification

- Pure policy tests cover migration, cycle rejection, reparenting, deletion promotion, duplicate names, and recipe assignment reconciliation.
- Swift package tests pass.
- ReciApp builds for iOS Simulator.
- Simulator inspection covers root folders, nested navigation, editors, layout switches, selection, and drag targets when a booted simulator is available.

## Non-goals

- No Supabase schema or Render API change: existing product decisions keep organization metadata on device.
- No cross-device folder synchronization.
- No partial selection inside the destructive folder-deletion sheet.
