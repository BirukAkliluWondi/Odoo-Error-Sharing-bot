import warnings
import sqlite3
import os
import io
from PIL import Image
import pytesseract
import logging

# Set up logging to see what's happening
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Silence PTB ConversationHandler mixed-handler warning
warnings.filterwarnings(
    "ignore",
    message=r"If 'per_message=False', 'CallbackQueryHandler' will not be tracked",
    category=UserWarning,
)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ConversationHandler,
    CallbackContext
)

# ── 1. CONFIGURATION & DATABASE ──────────────────────────────────────────
BOT_TOKEN = 'YOUR_TELEGRAM_BOT_API_KEY'  # Consider using environment variables for security
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# FIX: Use Absolute Path to ensure DB is saved in the script's folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, 'odoo_errors.db')

# Fix: Better database connection handling
def get_db_connection():
    """Get a database connection with row factory for better access"""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # This allows column access by name
    return conn

# Initialize database
conn = get_db_connection()
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        error_message TEXT NOT NULL,
        description TEXT NOT NULL,
        solution TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
conn.commit()

# Conversation states
CHOICE, TEXT_ERROR, TEXT_DESC, TEXT_SOLUTION, PHOTO_ERROR, PHOTO_DESC, PHOTO_SOLUTION = range(7)

# ── 2. GENERAL HANDLERS ──────────────────────────────────────────────────────

async def start(update: Update, context: CallbackContext) -> None:
    """Start command handler"""
    await update.message.reply_text(
        'Welcome to Odoo Error Bot! 🚀 (Host Mode)\n\n'
        '• Use /post to add a new error\n'
        '• Use /search <keyword> to find solutions\n'
        '• Send a photo directly for an OCR-based search.'
    )

async def cancel(update: Update, context: CallbackContext) -> int:
    """Cancel the current conversation"""
    await update.message.reply_text("Action cancelled.")
    context.user_data.clear()
    return ConversationHandler.END

# ── 3. POSTING FLOW (TEXT & IMAGE) ──────────────────────────────────────────

async def post_start(update: Update, context: CallbackContext) -> int:
    """Start the posting process"""
    logger.info(f"User {update.effective_user.id} started /post command")
    
    keyboard = [[
        InlineKeyboardButton("📝 Text Mode", callback_data='text'),
        InlineKeyboardButton("🖼️ Image Mode", callback_data='image')
    ]]
    
    await update.message.reply_text(
        'How would you like to share the error?',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOICE

async def handle_choice(update: Update, context: CallbackContext) -> int:
    """Handle the user's choice between text and image mode"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'text':
        await query.edit_message_text("Please type the **Error Message**:")
        return TEXT_ERROR
    else:
        await query.edit_message_text("Please send the **Screenshot** of the error:")
        return PHOTO_ERROR

# --- Text Path ---
async def text_error(update: Update, context: CallbackContext) -> int:
    """Handle text error input"""
    context.user_data['error'] = update.message.text.strip()
    await update.message.reply_text("Now, send the **Description**:")
    return TEXT_DESC

async def text_desc(update: Update, context: CallbackContext) -> int:
    """Handle text description input"""
    context.user_data['desc'] = update.message.text.strip()
    await update.message.reply_text("Finally, send the **Solution**:")
    return TEXT_SOLUTION

async def text_solution(update: Update, context: CallbackContext) -> int:
    """Handle text solution input and save to database"""
    sol = update.message.text.strip()
    err = context.user_data.get('error')
    dsc = context.user_data.get('desc')
    
    if not all([err, dsc, sol]):
        await update.message.reply_text("❌ Missing data. Please start over with /post")
        context.user_data.clear()
        return ConversationHandler.END
    
    try:
        cursor.execute('INSERT INTO posts (error_message, description, solution) VALUES (?, ?, ?)', 
                      (err, dsc, sol))
        conn.commit()
        await update.message.reply_text("✅ Successfully saved to the central database!")
    except Exception as e:
        logger.error(f"Database error: {e}")
        await update.message.reply_text("❌ Failed to save to database. Please try again.")
    
    context.user_data.clear()
    return ConversationHandler.END

# --- Image Path (with High-Accuracy OCR) ---
# --- Image Path (with Enhanced OCR for ALL text) ---
async def photo_error(update: Update, context: CallbackContext) -> int:
    """Handle photo input and perform OCR to capture ALL text"""
    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        img_bytes = await file.download_as_bytearray()
        
        # Open image and enhance for better text detection
        img = Image.open(io.BytesIO(img_bytes))
        
        # Resize if too large (helps with small text)
        max_size = 2000
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Convert to grayscale
        img = img.convert('L')
        
        # Enhance contrast
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)
        
        # Try multiple PSM modes to capture ALL text
        configs = [
            r'--oem 3 --psm 6',      # Assume uniform block (good for paragraphs)
            r'--oem 3 --psm 3',      # Automatic with OSD
            r'--oem 3 --psm 4',      # Single column
            r'--oem 3 --psm 11',     # Sparse text
            r'--oem 3 --psm 12',     # Sparse text with OSD
            r'--oem 3 --psm 1',      # Automatic with OSD
        ]
        
        extracted = ""
        best_text = ""
        best_length = 0
        
        # Try each config and keep the best result
        for config in configs:
            try:
                text = pytesseract.image_to_string(img, config=config).strip()
                if len(text) > best_length:
                    best_length = len(text)
                    best_text = text
            except:
                continue
        
        # Also try with page segmentation disabled for maximum capture
        try:
            text = pytesseract.image_to_string(img, config=r'--oem 3 --psm 0').strip()
            if len(text) > best_length:
                best_length = len(text)
                best_text = text
        except:
            pass
        
        # Get the best result
        extracted = best_text
        
        if not extracted:
            # Last resort: basic config
            extracted = pytesseract.image_to_string(img).strip()
        
        if not extracted:
            await update.message.reply_text(
                "❌ OCR could not read the text. Please:\n"
                "1. Try a clearer screenshot with larger text\n"
                "2. Use /post and select Text Mode\n"
                "3. Type /cancel to abort"
            )
            return PHOTO_ERROR
            
        context.user_data['error'] = extracted
        preview = extracted[:500] + "..." if len(extracted) > 500 else extracted
        await update.message.reply_text(
            f"📖 **Full Text Captured:**\n\n{preview}\n\n"
            f"Now send the **Description**:"
        )
        return PHOTO_DESC
        
    except Exception as e:
        logger.error(f"OCR Error: {e}")
        await update.message.reply_text(f"❌ OCR Error: {str(e)[:100]}")
        return PHOTO_ERROR

async def photo_desc(update: Update, context: CallbackContext) -> int:
    """Handle description after photo"""
    context.user_data['desc'] = update.message.text.strip()
    await update.message.reply_text("Send the **Solution**:")
    return PHOTO_SOLUTION

async def photo_solution(update: Update, context: CallbackContext) -> int:
    """Handle solution after photo and save to database"""
    sol = update.message.text.strip()
    err = context.user_data.get('error')
    dsc = context.user_data.get('desc')
    
    if not all([err, dsc, sol]):
        await update.message.reply_text("❌ Missing data. Please start over with /post")
        context.user_data.clear()
        return ConversationHandler.END
    
    try:
        cursor.execute('INSERT INTO posts (error_message, description, solution) VALUES (?, ?, ?)', 
                      (err, dsc, sol))
        conn.commit()
        await update.message.reply_text("✅ Successfully saved with OCR data!")
    except Exception as e:
        logger.error(f"Database error: {e}")
        await update.message.reply_text("❌ Failed to save to database. Please try again.")
    
    context.user_data.clear()
    return ConversationHandler.END

# ── 4. SEARCHING FLOW ────────────────────────────────────────────────────────

async def search(update: Update, context: CallbackContext) -> None:
    """Search for solutions in the database"""
    if not context.args:
        await update.message.reply_text("Usage: /search <keyword>")
        return

    query = ' '.join(context.args).lower()
    
    try:
        cursor.execute(
            "SELECT * FROM posts WHERE LOWER(error_message) LIKE ? OR LOWER(description) LIKE ? ORDER BY created_at DESC LIMIT 5",
            (f'%{query}%', f'%{query}%')
        )
        results = cursor.fetchall()

        if not results:
            await update.message.reply_text("No results found in the community database.")
            return

        response = "🔍 **Community Solutions Found:**\n\n"
        for row in results:
            response += f"⚠️ **Error:** {row[1][:100]}...\n💡 **Solution:** {row[3]}\n---\n"
        
        # Split long messages if needed
        if len(response) > 4096:
            for x in range(0, len(response), 4096):
                await update.message.reply_text(response[x:x+4096], parse_mode='Markdown')
        else:
            await update.message.reply_text(response, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Search error: {e}")
        await update.message.reply_text("❌ Search failed. Please try again.")

async def handle_photo_search(update: Update, context: CallbackContext) -> None:
    """Handle photo search with enhanced OCR to capture ALL text"""
    # Don't process if user is in a conversation
    if context.user_data:
        return

    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        img_bytes = await file.download_as_bytearray()
        
        # Open and enhance image
        img = Image.open(io.BytesIO(img_bytes))
        
        # Resize if too large
        max_size = 2000
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Convert to grayscale and enhance
        img = img.convert('L')
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)
        
        # Try multiple configs to get all text
        configs = [
            r'--oem 3 --psm 6',
            r'--oem 3 --psm 3',
            r'--oem 3 --psm 4',
            r'--oem 3 --psm 11',
            r'--oem 3 --psm 0',
        ]
        
        best_text = ""
        best_length = 0
        
        for config in configs:
            try:
                text = pytesseract.image_to_string(img, config=config).strip()
                if len(text) > best_length:
                    best_length = len(text)
                    best_text = text
            except:
                continue
        
        extracted = best_text
        
        if not extracted:
            # Fallback to basic config
            extracted = pytesseract.image_to_string(img).strip()
        
        if not extracted:
            return

        # Show preview of captured text
        preview = extracted[:200] + "..." if len(extracted) > 200 else extracted
        await update.message.reply_text(f"📖 **OCR Captured:** {preview}")

        # Extract meaningful keywords from ALL text
        words = extracted.split()
        # Filter for meaningful words (longer than 3 chars)
        keywords = [w for w in words if len(w) > 3 and w.isalpha()]
        
        if keywords:
            # Use first 10 keywords for search
            search_terms = ' '.join(keywords[:10]).lower()
            
            cursor.execute(
                "SELECT * FROM posts WHERE LOWER(error_message) LIKE ? OR LOWER(description) LIKE ? OR LOWER(solution) LIKE ? LIMIT 5",
                (f'%{search_terms}%', f'%{search_terms}%', f'%{search_terms}%')
            )
            results = cursor.fetchall()

            if results:
                resp = "✅ **Found matching solutions:**\n\n"
                for r in results:
                    resp += f"⚠️ **Error:** {r[1][:100]}...\n💡 **Solution:** {r[3][:100]}...\n---\n"
                
                if len(resp) > 4096:
                    for x in range(0, len(resp), 4096):
                        await update.message.reply_text(resp[x:x+4096], parse_mode='Markdown')
                else:
                    await update.message.reply_text(resp, parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ No matches found. Try /search with keywords or /post to add this solution.")
        else:
            await update.message.reply_text("❌ No valid keywords found in image.")
            
    except Exception as e:
        logger.error(f"Photo search error: {e}")
        # Silently fail - don't bother user with errors for auto-search

# ── 5. MAIN EXECUTION ────────────────────────────────────────────────────────

def main():
    """Main function to run the bot"""
    try:
        # Verify database connection
        cursor.execute("SELECT 1")
        logger.info(f"Database connected successfully at: {db_path}")
        
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        
        # Create conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("post", post_start)],
            states={
                CHOICE: [CallbackQueryHandler(handle_choice)],
                TEXT_ERROR: [MessageHandler(filters.TEXT & ~filters.COMMAND, text_error)],
                TEXT_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, text_desc)],
                TEXT_SOLUTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, text_solution)],
                PHOTO_ERROR: [MessageHandler(filters.PHOTO, photo_error)],
                PHOTO_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, photo_desc)],
                PHOTO_SOLUTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, photo_solution)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            name="post_conversation",
            persistent=False,
        )
        
        # Add handlers in correct order
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("search", search))
        app.add_handler(conv_handler)
        # Photo handler should be last as it's a catch-all for photos
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo_search))
        
        logger.info("Bot is starting...")
        print(f"✅ Bot is active. Database located at: {db_path}")
        print("✅ Press Ctrl+C to stop")
        
        app.run_polling()
        
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        print(f"❌ Failed to start bot: {e}")

if __name__ == "__main__":

    main()
