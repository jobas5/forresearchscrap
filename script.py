import asyncio
import json
import csv
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError

# ---------------------------
# CONFIG
# ---------------------------
# GANTI LINK COPY PASTE DARI X.COM DARI ADVANCE SEARCH
SEARCH_URL = "https://x.com/search?q=sosial%20media%20stress&src=typed_query&f=live" 
OUTPUT_JSON = "tweets.json"
OUTPUT_CSV = "tweets.csv"
MAX_SCROLLS = 20 # INI UNTUK MENGATUR BERAPA KALI MAU SCROLL EFEK KE BANYAK DATA
SCROLL_WAIT = 2.0

USER_DATA_DIR = Path("user_data")  # Persistent session folder
NAV_RETRIES = 3
NAV_TIMEOUT = 60000  # 60 seconds

# ---------------------------
# FUNCTIONS
# ---------------------------
async def safe_goto(page, url):
    """Navigate with retry logic and exponential backoff."""
    for attempt in range(NAV_RETRIES):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            return
        except TimeoutError as e:
            print(f"⚠️ Navigation timeout (attempt {attempt+1}): {e}")
        except Exception as e:
            print(f"⚠️ Navigation error (attempt {attempt+1}): {e}")
        await asyncio.sleep(5 * (attempt + 1))
    raise Exception("❌ Failed to navigate after retries.")

async def scrape_tweets():
    async with async_playwright() as p:
        # Launch persistent context
        browser_context = await p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            args=["--start-maximized"]
        )

        page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()

        # Stealth mode
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });
            Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
        """)

        print("🔎 Navigating to search page...")
        await safe_goto(page, SEARCH_URL)

        print("✅ If login page appears, log in manually. Session will be saved for next runs.")
        await page.wait_for_selector("div[data-testid='cellInnerDiv']", timeout=60000)

        tweets = []
        seen_links = set()

        # ---------------------------
        # SCRAPING LOOP
        # ---------------------------
        for i in range(MAX_SCROLLS):
            try:
                # Scroll down
                await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                await asyncio.sleep(SCROLL_WAIT)

                # Use Locator instead of ElementHandle
                articles = page.locator("div[data-testid='cellInnerDiv']")
                count = await articles.count()
                print(f"🔍 Found {count} tweet containers on scroll {i+1}")

                for idx in range(count):
                    article = articles.nth(idx)  # Locator for each tweet

                    try:
                        # Username & Handle
                        username, handle = None, None
                        try:
                            name_spans = await article.locator("div[data-testid='User-Name'] span").all_text_contents()
                            for span in name_spans:
                                if span.startswith("@"):
                                    handle = span.strip()
                                elif username is None:
                                    username = span.strip()
                        except Exception as e:
                            print(f"⚠️ Username/Handle extraction failed: {e}")

                        # Tweet text
                        text = None
                        try:
                            text = await article.locator("div[data-testid='tweetText']").inner_text()
                        except:
                            text = await article.inner_text()

                        # Timestamp & Tweet link
                        timestamp, tweet_link = None, None
                        try:
                            time_el = article.locator("time")
                            if await time_el.count() > 0:
                                timestamp = await time_el.get_attribute("datetime")
                                parent_a = await time_el.evaluate_handle("t => t.parentElement")
                                if parent_a:
                                    href = await parent_a.get_property("href")
                                    tweet_link = await href.json_value()
                        except Exception as e:
                            print(f"⚠️ Timestamp extraction failed: {e}")

                        # Images
                        images = []
                        try:
                            img_elements = article.locator("img")
                            img_count = await img_elements.count()
                            for j in range(img_count):
                                src = await img_elements.nth(j).get_attribute("src")
                                if src and "profile_images" not in src and "emoji" not in src:
                                    images.append(src)
                        except Exception as e:
                            print(f"⚠️ Image extraction failed: {e}")

                        # Debug info
                        print(f"Extracted -> Username: {username}, Handle: {handle}, Text: {text[:50] if text else 'None'}")

                        # Save tweet if unique
                        if tweet_link and tweet_link not in seen_links:
                            seen_links.add(tweet_link)
                            tweets.append({
                                "username": username or "",
                                "handle": handle or "",
                                "text": text.strip() if text else "",
                                "timestamp": timestamp or "",
                                "tweet_link": tweet_link or "",
                                "images": images
                            })

                    except Exception as e:
                        print(f"⚠️ Error processing article: {e}")
                        continue

                print(f"✅ Scroll {i+1}/{MAX_SCROLLS}: Collected {len(tweets)} tweets so far")

            except Exception as e:
                print(f"⚠️ Error during scroll {i+1}: {e}")
                continue

        # ---------------------------
        # SAVE RESULTS
        # ---------------------------
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(tweets, f, ensure_ascii=False, indent=2)

        with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as cf:
            writer = csv.writer(cf)
            writer.writerow(["username", "handle", "text", "timestamp", "tweet_link", "images"])
            for t in tweets:
                writer.writerow([
                    t.get("username"),
                    t.get("handle"),
                    t.get("text"),
                    t.get("timestamp"),
                    t.get("tweet_link"),
                    " | ".join(t.get("images") or [])
                ])

        print(f"🎉 Done! Saved {len(tweets)} tweets to {OUTPUT_JSON} and {OUTPUT_CSV}")
        await browser_context.close()

if __name__ == "__main__":
    asyncio.run(scrape_tweets())