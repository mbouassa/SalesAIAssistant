"""
Perception Service - DOM-first page state extraction.

Extracts structured information from any web page:
- URL, title, meta info
- Text content and structure
- Interactive elements (buttons, links, inputs)
- Accessibility tree for reliable targeting

This is the "eyes" of the demo agent - it sees what's on screen.
"""

import time
from dataclasses import dataclass, field
from typing import Optional
from playwright.async_api import Page


@dataclass
class ClickableElement:
    """A clickable element on the page."""
    role: str                    # button, link, menuitem, etc.
    name: str                    # Accessible name / visible text
    selector: str                # CSS selector for targeting
    tag: str                     # HTML tag (a, button, div, etc.)
    href: Optional[str] = None   # For links
    bounding_box: Optional[dict] = None  # {x, y, width, height} for future vision


@dataclass
class InputElement:
    """A form input element."""
    input_type: str              # text, email, password, etc.
    name: str                    # Accessible name / label
    selector: str                # CSS selector
    placeholder: Optional[str] = None
    value: Optional[str] = None  # Current value (masked for passwords)


@dataclass
class Heading:
    """A heading element for page structure."""
    level: int                   # 1-6 for h1-h6
    text: str
    selector: str


@dataclass
class PageState:
    """Complete snapshot of what's visible on the page."""
    # Basic info
    url: str
    domain: str
    title: str
    
    # Content
    text_summary: str            # Main visible text (truncated)
    headings: list[Heading] = field(default_factory=list)
    
    # Interactive elements
    clickables: list[ClickableElement] = field(default_factory=list)
    inputs: list[InputElement] = field(default_factory=list)
    
    # Meta
    extraction_time_ms: int = 0
    error: Optional[str] = None


class PerceptionService:
    """
    Extracts structured page state from a Playwright page.
    
    Usage:
        perception = PerceptionService()
        state = await perception.extract(page)
        print(state.title, state.clickables)
    """
    
    # Limits to prevent huge payloads
    MAX_TEXT_LENGTH = 2000
    MAX_CLICKABLES = 30
    MAX_INPUTS = 15
    MAX_HEADINGS = 10
    
    def __init__(self):
        self._log_prefix = "[Perception]"
    
    def _log(self, message: str, emoji: str = "📍") -> None:
        """Log with consistent formatting."""
        print(f"{self._log_prefix} {emoji} {message}", flush=True)
    
    async def extract(self, page: Page) -> PageState:
        """
        Extract complete page state from a Playwright page.
        
        Args:
            page: Playwright Page object
            
        Returns:
            PageState with all extracted information
        """
        start_time = time.time()
        self._log("Extracting page state...", "🔍")
        
        try:
            # Basic info
            url = page.url
            domain = url.split("//")[-1].split("/")[0] if "//" in url else url.split("/")[0]
            title = await page.title()
            
            self._log(f"URL: {url}", "📍")
            self._log(f"Title: {title}", "📄")
            
            # Extract all data in parallel-ish (single evaluate is faster)
            extraction = await page.evaluate("""
                () => {
                    const result = {
                        textContent: '',
                        headings: [],
                        clickables: [],
                        inputs: []
                    };
                    
                    // === TEXT CONTENT ===
                    // Try main content areas first, fall back to body
                    const contentAreas = ['main', 'article', '[role="main"]', '.content', '#content', 'body'];
                    let textSource = null;
                    for (const selector of contentAreas) {
                        textSource = document.querySelector(selector);
                        if (textSource && textSource.innerText.trim().length > 100) break;
                    }
                    if (textSource) {
                        result.textContent = textSource.innerText.slice(0, 3000);
                    }
                    
                    // === HEADINGS ===
                    const headings = document.querySelectorAll('h1, h2, h3');
                    headings.forEach((h, i) => {
                        if (i < 15 && h.innerText.trim()) {
                            const level = parseInt(h.tagName[1]);
                            result.headings.push({
                                level: level,
                                text: h.innerText.trim().slice(0, 100),
                                // Generate a unique selector
                                selector: h.id ? `#${h.id}` : `${h.tagName.toLowerCase()}:nth-of-type(${i + 1})`
                            });
                        }
                    });
                    
                    // === CLICKABLE ELEMENTS ===
                    // Use multiple strategies to find interactive elements
                    const clickableSelectors = [
                        'button:not([disabled])',
                        'a[href]',
                        '[role="button"]',
                        '[role="link"]',
                        '[role="menuitem"]',
                        '[onclick]',
                        'input[type="submit"]',
                        'input[type="button"]'
                    ];
                    
                    const seen = new Set();
                    clickableSelectors.forEach(selector => {
                        document.querySelectorAll(selector).forEach(el => {
                            // Skip if already seen or hidden
                            if (seen.has(el)) return;
                            if (el.offsetParent === null && el.tagName !== 'A') return; // Hidden
                            
                            const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
                            if (!text || text.length > 100) return;
                            
                            seen.add(el);
                            
                            // Determine role
                            let role = el.getAttribute('role') || el.tagName.toLowerCase();
                            if (role === 'a') role = 'link';
                            if (role === 'input') role = 'button';
                            
                            // Build a reliable selector
                            let cssSelector = '';
                            if (el.id) {
                                cssSelector = `#${el.id}`;
                            } else if (el.getAttribute('data-testid')) {
                                cssSelector = `[data-testid="${el.getAttribute('data-testid')}"]`;
                            } else if (el.className && typeof el.className === 'string') {
                                const classes = el.className.split(' ').filter(c => c && !c.includes(':'));
                                if (classes.length > 0) {
                                    cssSelector = `${el.tagName.toLowerCase()}.${classes.slice(0, 2).join('.')}`;
                                }
                            }
                            if (!cssSelector) {
                                cssSelector = `${el.tagName.toLowerCase()}:has-text("${text.slice(0, 30)}")`;
                            }
                            
                            // Get bounding box
                            const rect = el.getBoundingClientRect();
                            
                            result.clickables.push({
                                role: role,
                                name: text.slice(0, 50),
                                tag: el.tagName.toLowerCase(),
                                selector: cssSelector,
                                href: el.href || null,
                                boundingBox: {
                                    x: Math.round(rect.x),
                                    y: Math.round(rect.y),
                                    width: Math.round(rect.width),
                                    height: Math.round(rect.height)
                                }
                            });
                        });
                    });
                    
                    // Limit clickables
                    result.clickables = result.clickables.slice(0, 40);
                    
                    // === INPUT ELEMENTS ===
                    document.querySelectorAll('input, textarea, select').forEach(el => {
                        if (el.offsetParent === null) return; // Hidden
                        
                        const inputType = el.type || el.tagName.toLowerCase();
                        if (['hidden', 'submit', 'button'].includes(inputType)) return;
                        
                        // Get label
                        let label = '';
                        if (el.id) {
                            const labelEl = document.querySelector(`label[for="${el.id}"]`);
                            if (labelEl) label = labelEl.innerText.trim();
                        }
                        if (!label) {
                            label = el.getAttribute('aria-label') || el.placeholder || el.name || '';
                        }
                        
                        // Build selector
                        let cssSelector = '';
                        if (el.id) {
                            cssSelector = `#${el.id}`;
                        } else if (el.name) {
                            cssSelector = `${el.tagName.toLowerCase()}[name="${el.name}"]`;
                        }
                        
                        result.inputs.push({
                            inputType: inputType,
                            name: label.slice(0, 50),
                            selector: cssSelector,
                            placeholder: el.placeholder || null,
                            value: inputType === 'password' ? '***' : (el.value || '').slice(0, 20)
                        });
                    });
                    
                    result.inputs = result.inputs.slice(0, 20);
                    
                    return result;
                }
            """)
            
            # Process text
            text_summary = extraction.get('textContent', '')[:self.MAX_TEXT_LENGTH]
            self._log(f"Text: {len(text_summary)} chars extracted", "📝")
            
            # Process headings
            headings = [
                Heading(
                    level=h['level'],
                    text=h['text'],
                    selector=h['selector']
                )
                for h in extraction.get('headings', [])[:self.MAX_HEADINGS]
            ]
            if headings:
                self._log(f"Headings: {len(headings)} found", "📋")
                for h in headings[:3]:
                    self._log(f"  h{h.level}: \"{h.text[:40]}...\"" if len(h.text) > 40 else f"  h{h.level}: \"{h.text}\"", "  ")
            
            # Process clickables
            clickables = [
                ClickableElement(
                    role=c['role'],
                    name=c['name'],
                    selector=c['selector'],
                    tag=c['tag'],
                    href=c.get('href'),
                    bounding_box=c.get('boundingBox')
                )
                for c in extraction.get('clickables', [])[:self.MAX_CLICKABLES]
            ]
            self._log(f"Clickables: {len(clickables)} elements", "🔘")
            for c in clickables[:5]:
                self._log(f"  → {c.role}: \"{c.name}\" ({c.selector[:40]}...)" if len(c.selector) > 40 else f"  → {c.role}: \"{c.name}\" ({c.selector})", "  ")
            if len(clickables) > 5:
                self._log(f"  ... and {len(clickables) - 5} more", "  ")
            
            # Process inputs
            inputs = [
                InputElement(
                    input_type=i['inputType'],
                    name=i['name'],
                    selector=i['selector'],
                    placeholder=i.get('placeholder'),
                    value=i.get('value')
                )
                for i in extraction.get('inputs', [])[:self.MAX_INPUTS]
            ]
            if inputs:
                self._log(f"Inputs: {len(inputs)} fields", "✏️")
                for inp in inputs[:3]:
                    self._log(f"  → {inp.input_type}: \"{inp.name}\"", "  ")
            
            # Calculate timing
            extraction_time_ms = int((time.time() - start_time) * 1000)
            self._log(f"Extraction complete in {extraction_time_ms}ms", "✓")
            
            return PageState(
                url=url,
                domain=domain,
                title=title,
                text_summary=text_summary,
                headings=headings,
                clickables=clickables,
                inputs=inputs,
                extraction_time_ms=extraction_time_ms
            )
            
        except Exception as e:
            self._log(f"Extraction failed: {e}", "❌")
            return PageState(
                url=page.url if page else "unknown",
                domain="unknown",
                title="",
                text_summary="",
                error=str(e),
                extraction_time_ms=int((time.time() - start_time) * 1000)
            )
    
    def summarize_for_llm(self, state: PageState, max_length: int = 1500) -> str:
        """
        Create a concise summary of the page state for LLM context.
        
        Args:
            state: PageState from extract()
            max_length: Max characters for the summary
            
        Returns:
            Human-readable summary for LLM prompt
        """
        parts = []
        
        # Basic info
        parts.append(f"Page: {state.title}")
        parts.append(f"URL: {state.url}")
        parts.append("")
        
        # Headings (structure)
        if state.headings:
            parts.append("Page Structure:")
            for h in state.headings[:5]:
                indent = "  " * (h.level - 1)
                parts.append(f"{indent}- {h.text}")
            parts.append("")
        
        # Key content
        if state.text_summary:
            # Take first ~500 chars as the "above the fold" content
            content_preview = state.text_summary[:500].strip()
            if len(state.text_summary) > 500:
                content_preview += "..."
            parts.append(f"Content Preview:\n{content_preview}")
            parts.append("")
        
        # Available actions
        if state.clickables:
            parts.append("Available Actions:")
            for c in state.clickables[:10]:
                if c.role == "link":
                    parts.append(f"  - Click \"{c.name}\" (link)")
                else:
                    parts.append(f"  - Click \"{c.name}\" (button)")
            if len(state.clickables) > 10:
                parts.append(f"  ... and {len(state.clickables) - 10} more")
        
        summary = "\n".join(parts)
        
        # Truncate if needed
        if len(summary) > max_length:
            summary = summary[:max_length - 3] + "..."
        
        return summary


# Singleton instance
perception_service = PerceptionService()

