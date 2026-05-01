# Color Agent Plugins

This repository contains API plugins for a Color Composition Experiment Agent.

The agent helps design learners understand image color composition through the following workflow:

1. Upload an image.
2. Identify the top 4 dominant color regions.
3. Display color blocks, percentages, and approximate image regions.
4. Let the user adjust a selected color region using HSL sliders.
5. Generate a recolored preview image.
6. Compare the original image and the adjusted image.
7. Generate an AI-readable color analysis.

## MVP Scope

The first version should implement a FastAPI backend service with three API endpoints:

### POST /segment

Input:
- image file or image URL
- color_count, default 4

Output:
- top 4 color regions
- HEX / RGB / HSL values
- percentage
- role
- mask placeholder URL or path
- annotated preview placeholder URL or path

### POST /recolor

Input:
- image ID or image path
- target region ID
- new HSL values

Output:
- preview image placeholder URL or path
- adjusted color data
- before / after HSL
- change values

### POST /analyze

Input:
- original color regions
- adjusted color regions
- original image URL
- adjusted image URL
- optional user goal

Output:
- tags
- color relation
- visual feeling
- suitable scenario
- summary
- explanation
- risk
- next step

## Technical Direction

Use:

- Python
- FastAPI
- Pillow
- OpenCV
- NumPy
- scikit-learn if needed later

## Development Principle

Start with a runnable MVP first.

Do not implement precise Photoshop-level segmentation in the first version.
Do not build frontend UI in this repository.
Do not build the full AI agent in this repository.

This repository only provides callable API tools for the AI agent.
