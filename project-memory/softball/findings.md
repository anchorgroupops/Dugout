# Findings: Softball

## Research & Discoveries

- **Relationship to Announcer Project**: This project is an evolution of the `H:\Repos\Personal\Announcer` web app.
- **North Star**: A high-energy softball walk-up app that announces players ("Now batting... #7, [Name]!") using a Jeff Steitzer (Halo) voice clone, followed by a song snippet.
- **Voice Assets**: Found in `H:\Repos\Personal\Announcer\Inspa`.
- **Integrations**: ElevenLabs for TTS, NotebookLM for context.
- **Core Requirement**: Low latency and deterministic timing (Announcement -> Pause -> Song).

## Constraints & Limitations

- **ElevenLabs Access**: Need to verify API keys and voice IDs.
- **Audio Mixing**: Must be handled client-side or pre-rendered for zero lag.
- **Data Source**: Transitioning from ad-hoc JSON to a structured roster format.
