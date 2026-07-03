import asyncio
import json
import sys
from pathlib import Path
from typing import List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))

from config_loader import load_config
from scraper import TelegramChannelScraper
from output_generator import OutputGenerator


class DebugTelegramChannelScraper(TelegramChannelScraper):
    """
    نسخهٔ دیباگ با اسکرول هوشمند و شمارش دقیق تا limit
    """

    def __init__(self, config, debug_screenshots: bool = True):
        config.debug_mode = True
        super().__init__(config)
        self.debug_screenshots = debug_screenshots
        self.debug_screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info("🐞 حالت دیباگ فعال – دانلود رسانه غیرفعال است.")
        self.logger.info(f"🐞 پوشه اسکرین‌شات: {self.debug_screenshots_dir}")
        self._last_items = []

    async def _download_media(self, items: List[Dict], page, context) -> tuple[dict, int]:
        self.logger.info("🐞 دانلود رسانه در حالت دیباگ غیرفعال است.")
        return {}, 0

    async def _save_debug_screenshot(self, page, name: str, full_page=True):
        if not self.debug_screenshots:
            return
        try:
            await self._screenshot(page, name, full_page=full_page)
            self.logger.debug(f"📸 اسکرین‌شات دیباگ: {name}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره اسکرین‌شات: {e}")

    # ═══════════════════ متد اصلی استخراج با منطق دقیق ═══════════════════
    async def _fetch_posts_from_telegram(self) -> tuple[List[Dict], any, any]:
        self.logger.info("🐞 شروع استخراج پست‌ها با حلقهٔ دقیق تا limit...")
        page = None
        context = None
        try:
            # راه‌اندازی مرورگر و رفتن به کانال
            page, context = await self._setup_browser()
            await self._navigate_to_channel(page)
            await self._handle_login(page)

            # ─── ذخیره اسکرین‌شات اولیه ───
            await self._save_debug_screenshot(page, "initial_page")

            # ─── انتخابگر پست‌ها (مشابه کد اصلی) ───
            # در کد اصلی از '.tgme_widget_message' استفاده شده، اما ممکن است متفاوت باشد.
            # برای اطمینان، از همان انتخابی که در متد _collect_current_posts استفاده می‌شود، استفاده می‌کنیم.
            # (در صورتی که متد _collect_current_posts وجود ندارد، خودمان پیاده‌سازی می‌کنیم.)
            # برای سادگی، از یک تابع داخلی برای گرفتن پست‌های فعلی استفاده می‌کنیم.

            collected_ids = set()   # برای جلوگیری از تکرار
            all_items = []          # لیست نهایی پست‌ها
            no_new_count = 0        # شماره تلاش‌های بی‌نتیجه
            scroll_attempts = 0     # تعداد کل اسکرول‌ها
            max_scrolls = 200       # سقف اسکرول برای جلوگیری از حلقه بی‌نهایت

            # ─── حلقه اصلی ───
            while len(all_items) < self.limit and scroll_attempts < max_scrolls:
                # ۱. جمع‌آوری پست‌های فعلی صفحه
                current_posts = await self._collect_current_posts(page)
                new_posts = [p for p in current_posts if p['id'] not in collected_ids]

                if new_posts:
                    all_items.extend(new_posts)
                    collected_ids.update([p['id'] for p in new_posts])
                    self.logger.info(f"🔍 جمعاً {len(all_items)} پست (جدید: {len(new_posts)})")
                    no_new_count = 0   # ریست شمارندهٔ بی‌نتیجه
                else:
                    no_new_count += 1
                    self.logger.debug(f"⚠️ هیچ پست جدیدی در اسکرول شماره {scroll_attempts+1}")

                # ۲. اگر به limit رسیدیم یا سه بار پشت‌سر هم پست جدید نیامد، خارج شو
                if len(all_items) >= self.limit or no_new_count >= 3:
                    break

                # ۳. اسکرول به پایین با مکانیزم مطمئن
                await self._scroll_page_smart(page)

                # ۴. صبر برای بارگذاری محتوای جدید (با timeout)
                try:
                    await page.wait_for_selector(
                        ".tgme_widget_message:last-child", 
                        timeout=5000, 
                        state="visible"
                    )
                except:
                    # اگر سلکتور پیدا نشد، باز هم ادامه می‌دهیم
                    pass
                await asyncio.sleep(1.5)  # کمی صبر اضافی

                scroll_attempts += 1

                # اسکرین‌شات هر ۵ مرحله برای دیباگ
                if scroll_attempts % 5 == 0:
                    await self._save_debug_screenshot(page, f"scroll_step_{scroll_attempts}")

            # ─── پس از خروج از حلقه ───
            # برش به اندازه limit (در صورت بیشتر بودن)
            final_items = all_items[:self.limit]
            self.logger.info(f"✅ نهایی: {len(final_items)} پست استخراج شد (هدف: {self.limit})")

            # اسکرین‌شات نهایی
            await self._save_debug_screenshot(page, "final_collection")

            return final_items, context, page

        except Exception as e:
            self.logger.error(f"❌ خطا در استخراج: {e}", exc_info=True)
            if page:
                await self._save_debug_screenshot(page, "error_state")
            return [], context, page

    # ─── متدهای کمکی ──────────────────────────────────────

    async def _collect_current_posts(self, page):
        """
        جمع‌آوری پست‌های قابل‌مشاهده در صفحه و تبدیل به دیکشنری با کلید 'id'
        این متد مشابه متد اصلی است، اما برای دیباگ مستقل نوشته شده.
        """
        try:
            # اجرای جاوااسکریپت برای استخراج داده‌های پست‌ها
            posts = await page.evaluate('''
                () => {
                    const items = document.querySelectorAll('.tgme_widget_message');
                    const result = [];
                    items.forEach(el => {
                        // استخراج شناسه (از data-post یا استخراج از لینک)
                        const link = el.querySelector('a.tgme_widget_message_date');
                        let id = null;
                        if (link) {
                            const href = link.getAttribute('href');
                            const match = href.match(/\\/(\\d+)$/);
                            if (match) id = parseInt(match[1], 10);
                        }
                        if (!id) {
                            // fallback: استفاده از timestamp + متن (اما ممکن است تکراری شود)
                            const text = el.innerText.slice(0, 50);
                            id = text.length + Math.random();  // موقتی
                        }
                        result.push({
                            id: id,
                            text: el.innerText || '',
                            // دیگر فیلدها در صورت نیاز
                        });
                    });
                    return result;
                }
            ''')
            return posts
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در جمع‌آوری پست‌ها: {e}")
            return []

    async def _scroll_page_smart(self, page):
        """
        اسکرول هوشمند: ابتدا با Page Down، سپس با جاوااسکریپت به پایین صفحه.
        """
        try:
            # روش اول: ارسال کلید PageDown (معمولاً محتوای جدید لود می‌شود)
            await page.keyboard.press("PageDown")
            await asyncio.sleep(0.5)
            # روش دوم: اسکرول با جاوااسکریپت به ارتفاع دو برابر viewport
            await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
            await asyncio.sleep(0.5)
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در اسکرول: {e}")

    # ─── اورراید متد run برای ذخیره خلاصه ──────────────────

    async def run(self):
        await super().run()
        try:
            debug_json_path = self.base_dir / "debug_summary.json"
            summary = {
                "channel": self.channel,
                "limit": self.limit,
                "start_link": self.start_link,
                "total_posts": len(self._last_items),
                "debug_mode": True
            }
            with open(debug_json_path, 'w', encoding='utf-8') as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            self.logger.info(f"🐞 خلاصه دیباگ در {debug_json_path}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در ذخیره خلاصه: {e}")

    async def _run_impl(self):
        # ذخیره آیتم‌ها در _last_items برای خلاصه
        items, context, page = await self._fetch_posts_from_telegram()
        self._last_items = items

        if not items:
            self.logger.warning("هیچ پستی دریافت نشد.")
            if context:
                await context.close()
            return

        self.logger.info(f"📥 {len(items)} پست استخراج شد.")

        # تولید خروجی (با media_map خالی)
        try:
            gen = OutputGenerator(
                self.base_dir,
                self.channel,
                items,
                {},  # media_map خالی
                debug_mode=self.debug_mode
            )
            gen.run_all()
            self.logger.info(f"📁 فایل‌های خروجی در: {self.base_dir}")
        except Exception as e:
            self.logger.warning(f"⚠️ خطا در تولید خروجی: {e}")

        if context:
            await context.close()

        self.logger.info("✅ پایان دیباگ.")
