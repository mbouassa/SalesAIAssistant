"""
Browser Service using Browserbase.
Controls a remote browser for product demos.
"""

from typing import Optional
from playwright.async_api import async_playwright, Browser, Page
from browserbase import Browserbase

from app.core.config import get_settings


class BrowserSession:
    """Represents an active Browserbase session with Playwright control."""
    
    def __init__(
        self,
        session_id: str,
        connect_url: str,
        live_view_url: str,
        product_url: str
    ):
        self.session_id = session_id
        self.connect_url = connect_url
        self.live_view_url = live_view_url
        self.product_url = product_url
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self._playwright = None
    
    async def connect(self) -> None:
        """Connect to the Browserbase session via Playwright."""
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.connect_over_cdp(self.connect_url)
        
        # Get existing context and page
        context = self.browser.contexts[0]
        self.page = context.pages[0] if context.pages else await context.new_page()
        
        # Navigate to product URL
        await self.page.goto(self.product_url, wait_until="domcontentloaded")
        print(f"[Browser] Navigated to: {self.product_url}", flush=True)
    
    async def click(self, selector: str, timeout: int = 1500) -> bool:
        """Click an element on the page. Fast timeout for quick fallback."""
        if not self.page:
            return False
        try:
            await self.page.click(selector, timeout=timeout)
            print(f"[Browser] Clicked: {selector}", flush=True)
            return True
        except Exception as e:
            # Don't log full error for timeout - too verbose
            if "Timeout" in str(e):
                pass  # Silent fail for timeout, we'll try next selector
            else:
                print(f"[Browser] Click failed: {e}", flush=True)
            return False
    
    async def smart_click(self, text: str, timeout: int = 2000) -> bool:
        """
        Smart click using Playwright's built-in locators.
        These are designed to find the right clickable element automatically.
        """
        if not self.page:
            return False
        
        try:
            # Strategy 1: getByRole with name (best for buttons/links with text)
            # This finds buttons, links, etc. by their accessible name
            for role in ['button', 'link', 'menuitem', 'tab']:
                try:
                    locator = self.page.get_by_role(role, name=text, exact=False)
                    if await locator.count() > 0:
                        await locator.first.click(timeout=timeout)
                        print(f"[Browser] Clicked {role} '{text}'", flush=True)
                        return True
                except Exception:
                    pass
            
            # Strategy 2: getByText (finds any element with this text)
            try:
                locator = self.page.get_by_text(text, exact=False)
                if await locator.count() > 0:
                    # Click the first visible one
                    await locator.first.click(timeout=timeout)
                    print(f"[Browser] Clicked text '{text}'", flush=True)
                    return True
            except Exception:
                pass
            
            # Strategy 3: Find by text and click nearest clickable ancestor
            try:
                result = await self.page.evaluate("""
                    (targetText) => {
                        // Find smallest element containing the exact text
                        const walker = document.createTreeWalker(
                            document.body,
                            NodeFilter.SHOW_TEXT,
                            null,
                            false
                        );
                        
                        let node;
                        while (node = walker.nextNode()) {
                            if (node.textContent.toLowerCase().includes(targetText.toLowerCase())) {
                                // Found text node, now find clickable parent
                                let el = node.parentElement;
                                let maxDepth = 5; // Don't go more than 5 levels up
                                
                                while (el && maxDepth > 0) {
                                    const tag = el.tagName.toLowerCase();
                                    const role = el.getAttribute('role');
                                    const hasClick = el.onclick || el.getAttribute('onclick');
                                    const cursor = window.getComputedStyle(el).cursor;
                                    
                                    // Check if this element is clickable
                                    if (tag === 'button' || tag === 'a' || 
                                        role === 'button' || hasClick || cursor === 'pointer') {
                                        el.click();
                                        return { 
                                            success: true, 
                                            tag: tag,
                                            text: el.innerText?.slice(0, 30) 
                                        };
                                    }
                                    
                                    el = el.parentElement;
                                    maxDepth--;
                                }
                            }
                        }
                        return { success: false };
                    }
                """, text)
                
                if result and result.get('success'):
                    print(f"[Browser] JS clicked <{result.get('tag')}> '{result.get('text')}'", flush=True)
                    return True
            except Exception:
                pass
            
            return False
                
        except Exception as e:
            print(f"[Browser] Smart click error: {e}", flush=True)
            return False
    
    async def scroll(self, direction: str = "down", amount: int = 300) -> bool:
        """Scroll the page."""
        if not self.page:
            return False
        try:
            delta = amount if direction == "down" else -amount
            await self.page.mouse.wheel(0, delta)
            print(f"[Browser] Scrolled {direction} by {amount}px", flush=True)
            return True
        except Exception as e:
            print(f"[Browser] Scroll failed: {e}", flush=True)
            return False
    
    async def type_text(self, selector: str, text: str) -> bool:
        """Type text into an input field."""
        if not self.page:
            return False
        try:
            await self.page.fill(selector, text)
            print(f"[Browser] Typed into {selector}", flush=True)
            return True
        except Exception as e:
            print(f"[Browser] Type failed: {e}", flush=True)
            return False
    
    async def navigate(self, url: str) -> bool:
        """Navigate to a different URL."""
        if not self.page:
            return False
        try:
            await self.page.goto(url, wait_until="domcontentloaded")
            print(f"[Browser] Navigated to: {url}", flush=True)
            return True
        except Exception as e:
            print(f"[Browser] Navigate failed: {e}", flush=True)
            return False
    
    async def get_page_content(self) -> dict:
        """Get page URL, title, text content, and clickable elements."""
        if not self.page:
            return {}
        
        try:
            url = self.page.url  # Get current URL
            title = await self.page.title()
            
            # Get main text content
            text_content = await self.page.evaluate("""
                () => {
                    const main = document.querySelector('main') || document.body;
                    return main.innerText.slice(0, 3000);
                }
            """)
            
            # Get clickable elements (buttons, links, icons with click handlers)
            clickables = await self.page.evaluate("""
                () => {
                    const elements = [];
                    const buttons = document.querySelectorAll('button, a, [role="button"], [onclick], svg[role="img"]');
                    buttons.forEach((el, i) => {
                        if (i < 30) {
                            let text = el.innerText?.trim() || el.getAttribute('aria-label') || el.getAttribute('title') || '';
                            // Sanitize: replace newlines/tabs with space, collapse multiple spaces
                            text = text.replace(/[\\n\\r\\t]+/g, ' ').replace(/\\s+/g, ' ').trim();
                            if (text) {
                                elements.push({
                                    text: text.slice(0, 50),
                                    tag: el.tagName.toLowerCase()
                                });
                            }
                        }
                    });
                    return elements;
                }
            """)
            
            return {
                "url": url,
                "title": title,
                "text_content": text_content,
                "clickable_elements": clickables
            }
        except Exception as e:
            print(f"[Browser] Get content failed: {e}", flush=True)
            return {}
    
    async def close(self) -> None:
        """Close the browser session."""
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()
        print(f"[Browser] Session {self.session_id} closed", flush=True)


class BrowserService:
    """Service for managing Browserbase sessions."""
    
    def __init__(self):
        settings = get_settings()
        self.client = Browserbase(api_key=settings.browserbase_api_key)
        self.project_id = settings.browserbase_project_id
        self._sessions: dict[str, BrowserSession] = {}
    
    async def create_session(self, room_name: str, product_url: str) -> BrowserSession:
        """Create a new Browserbase session for a room."""
        print(f"[Browser] Creating session for room: {room_name}", flush=True)
        
        # Create Browserbase session
        session = self.client.sessions.create(project_id=self.project_id)
        
        # Get debug URLs for live view
        debug_info = self.client.sessions.debug(session.id)
        live_view_url = debug_info.debugger_fullscreen_url
        
        print(f"[Browser] Session created: {session.id}", flush=True)
        print(f"[Browser] Live view URL: {live_view_url}", flush=True)
        
        # Create our session wrapper
        browser_session = BrowserSession(
            session_id=session.id,
            connect_url=session.connect_url,
            live_view_url=live_view_url,
            product_url=product_url
        )
        
        # Connect and navigate to product
        await browser_session.connect()
        
        # Store session
        self._sessions[room_name] = browser_session
        
        return browser_session
    
    def get_session(self, room_name: str) -> Optional[BrowserSession]:
        """Get an existing browser session for a room."""
        return self._sessions.get(room_name)
    
    async def close_session(self, room_name: str) -> None:
        """Close and cleanup a browser session."""
        if room_name in self._sessions:
            session = self._sessions.pop(room_name)
            await session.close()


# Singleton instance
browser_service = BrowserService()

