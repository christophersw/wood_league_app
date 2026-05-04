---
id: 16
title: Game Analysis Page Rewrite
status: open
priority: high
labels:
    - rewrite
created: "2026-05-04"
updated: "2026-05-04"
---

Rewrite (replace) the game board analysis page, with an eye towards testability, reliability, and performance. Many of the controls on this page are all connected by the notion of 'current ply'. The Move analysis elements (Board, PGN, Stockfish, and Lc0) are all aware of the current ply and highlighted it in their own way. They are all interactive, and let you select a move which sets the current ply for all the other elements. They stay in sync. The URL should update to show the current ply as query string, so that a person could share a link with the current ply embedded.

The page should have the following independent Elements that load and interact with each other through current ply:

## Title and Front Matter (does not care about current ply)

- Keep the current game meta data, titles, and information, but need to be designed with our new principles and patterns
- "Flip board" is a command that should go with the Board (see below)
- Opening needs to display as the Lichess named opening name (lookup from database), and need to link to the opening page for that opening.
- Write unit tests to ensure this works properly.

## Engine Analysis Section (also does not care about the current ply)

### Stockfish Analysis
- In an "Engine Analysis" Section
- Base this element on the existing one
- Rework the code and css displaying the bars to be consistent and visually striking, keep our design philosophy in mind.
- Move the Brilliant, Best, Great, etc. label numbers into the graphic. This is more consistent with the Du Bois approach.
- Element needs to contain a button to queue the analysis for a re-run. This needs to open a modal that confirms the user understands rerunning costs real money and electricity.
  - Users cannot queue an already queued game - this needs to be reflected by the UI and enforced by the queueing system.
- Write unit tests to ensure this works properly.

### Lc0 Analysis
- In an "Engine Analysis" Section
- Base this element on the existing Lc0 stats
- Rework the code and css displaying the bars to be consistent and visually striking, keep our design philosophy in mind.
- Move the Brilliant, Best, Great, etc. label numbers into the graphic. This is more consistent with the Du Bois approach.
- Element needs to contain a button to queue the analysis for a re-run. This needs to open a modal that confirms the user understands rerunning costs real money and electricity.
  - Users cannot queue an already queued game - this needs to be reflected by the UI and enforced by the queueing system.
- Write unit tests to ensure this works properly.

## Move-by-move Analysis

### Board
- In the Move-by-move analysis section
- Display the game moves
- Allow user to flip positions (black or white perspective)
- Show the top three moves from stockfish per ply, color shading them by relative improvement over the move made, and labeling them on the move-to square with an increase in cps.
- Show the top three moves from lc0 per ply, color shading them by relative improvement over the move made, and labeling them on the move-to square with an increase in cps.
- Allow the user to show/hide the stockfish and lc0 arrows. Showing and hiding should not reload board or change the move player is looking at.
- Automatically animate through the moves, with controls for pausing, next and previous
- The board element should NOT display the PGN, that's a separate element.
- Write unit tests to ensure this works properly.

### PGN
- In the Move-by-move analysis section
- There should be a dedicated element to display the PGN.
- It should link to the board, so that whatever move is shown on the board is highlighted in the PGN display.
- PGN display should be a simple table with a row for each move, with black and white as columns
- Moves would be colored using a consistent color pattern used in the stockfish and Lc0 graphs
- There should be a column next to each ply with iconography for blunder, great move, etc.
- Clicking on a ply in the table should set the board to that move, as well as set all the 'current ply' arrows.
- Write unit tests to ensure this works properly.

### Lc0 Move Analysis Chart
- Base this on the existing one
- Rework as needed to better conform to the updated look and feel
- Rework the existing one to be consistent with HTMX, ensure it is reliable, updates current highlight position with current ply, and support clicking on a ply to change current ply.
- Write unit tests to ensure this works properly.

### Stockfish Move Analysis Chart
- Base this on the existing one
- Rework as needed to better conform to the updated look and feel
- Rework the existing one to be consistent with HTMX, ensure it is reliable, updates arrow position with current ply, and support clicking on a ply to change current ply.
- Write unit tests to ensure this works properly.

## Design
- Typeset all elements in the way Du Bois would — clean, graphically striking. Use font sizes 40 year olds can read clearly.
- Make sure the layout is responsive, and works on mobile.
