# Company Personas

This directory contains company-specific AI persona configurations.

## How It Works

Each YAML file defines the AI's personality, product knowledge, and demo behavior for a specific company. The filename (without `.yaml`) is the `company_id` used to load the persona.

## Creating a New Persona

1. Copy `sample_company.yaml` to a new file: `your_company_id.yaml`
2. Edit the fields to match your company's product and style
3. Pass the `company_id` when initializing the PresenterService

## Configuration Fields

| Field | Description |
|-------|-------------|
| `name` | The AI's name (e.g., "Alex", "Sam") |
| `company` | Your company name |
| `role` | The AI's role (e.g., "Product Specialist", "Demo Engineer") |
| `tone` | Personality descriptors (e.g., "friendly, professional") |
| `speaking_style` | How the AI speaks (e.g., "concise, conversational") |
| `product_name` | Your product's name |
| `product_description` | One-line product description |
| `key_features` | List of features to highlight |
| `value_propositions` | Key benefits for customers |
| `common_objections` | Map of objections → response approaches |
| `demo_intro` | Opening line for the demo |
| `demo_outro` | Closing line for the demo |

## Usage

```python
from app.services.presenter_service import PresenterService

# Load company-specific persona
presenter = PresenterService(company_id="your_company_id")

# Or use default persona
presenter = PresenterService()
```

## Tips

- Keep `demo_intro` and `demo_outro` short (voice, not text)
- `tone` and `speaking_style` directly influence the AI's output
- `common_objections` helps the AI handle pushback naturally
- Add features you want highlighted in order of importance

