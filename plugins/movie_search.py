import aiohttp
from pyrogram import Client, filters
from pyrogram.types import (
    Message, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    CallbackQuery, 
    InputMediaPhoto
)

# A fallback image if the API doesn't provide a poster
FALLBACK_POSTER = "https://via.placeholder.com/800x1200.png?text=No+Poster+Available"

# --- HELPER FUNCTIONS ---

async def fetch_movie_data(query: str):
    """Fetches the raw JSON data from the API."""
    api_url = f"https://imdb.iamidiotareyoutoo.com/search?q={query}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(api_url) as response:
                if response.status == 200:
                    return await response.json()
        except Exception:
            return None
    return None

def build_movie_caption(movie: dict):
    """Formats the JSON movie data into a clean Telegram caption."""
    title = movie.get("#TITLE", "Unknown Title")
    year = movie.get("#YEAR", "Unknown Year")
    imdb_id = movie.get("#IMDB_ID", "Unknown ID")
    rank = movie.get("#RANK", "N/A")
    actors = movie.get("#ACTORS", "Not listed")
    aka = movie.get("#AKA", "N/A")
    imdb_url = movie.get("#IMDB_URL", f"https://www.imdb.com/title/{imdb_id}")
    
    return (
        f"🎬 **{title}** ({year})\n\n"
        f"🎭 **Actors:** {actors}\n"
        f"🏷️ **Also Known As:** {aka}\n"
        f"📈 **IMDb Rank:** {rank}\n"
        f"🆔 **IMDb ID:** `{imdb_id}`\n"
        f"🔗 **IMDb Link:** [Click Here]({imdb_url})\n\n"
        f"⚡ **Search by ID:** `/movie {imdb_id}`"
    )

def build_pagination_keyboard(page: int, total_results: int, query: str):
    """Builds the Next/Prev inline keyboard."""
    buttons = []
    
    # Telegram limits callback_data to 64 bytes, so we truncate the query if needed
    short_query = query[:40] 

    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"mov_{page-1}_{short_query}"))
    
    if page < total_results - 1:
        buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"mov_{page+1}_{short_query}"))
        
    return InlineKeyboardMarkup([buttons]) if buttons else None


# --- MAIN COMMAND HANDLER ---

@Client.on_message(filters.command("movie"))
async def movie_search_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Please provide a movie name!\n**Example:** `/movie Spiderman`")
    
    query = " ".join(message.command[1:])
    status_msg = await message.reply_text(f"🔍 Searching for `{query}`...")

    data = await fetch_movie_data(query)
    
    if not data or "description" not in data or not data["description"]:
        return await status_msg.edit_text("🤷‍♂️ No results found for that query or the API is down.")
    
    # Start at the first result (Index 0)
    results = data["description"]
    movie = results[0]
    
    caption = build_movie_caption(movie)
    image_url = movie.get("#IMG_POSTER", FALLBACK_POSTER)
    markup = build_pagination_keyboard(page=0, total_results=len(results), query=query)
    
    # Send the photo with the caption underneath, just like your reference image
    await message.reply_photo(
        photo=image_url, 
        caption=caption, 
        reply_markup=markup
    )
    await status_msg.delete()


# --- PAGINATION CALLBACK HANDLER ---

@Client.on_callback_query(filters.regex(r"^mov_(\d+)_(.*)$"))
async def movie_pagination_callback(client: Client, callback_query: CallbackQuery):
    # Parse the page number and query from the callback data
    page = int(callback_query.matches[0].group(1))
    query = callback_query.matches[0].group(2)
    
    # Let Telegram know we received the click
    await callback_query.answer("Loading page...")

    data = await fetch_movie_data(query)
    if not data or "description" not in data:
        return await callback_query.answer("Error fetching data.", show_alert=True)
    
    results = data["description"]
    
    # Ensure the page number is within bounds
    if page >= len(results) or page < 0:
        return await callback_query.answer("Page not found.", show_alert=True)
    
    movie = results[page]
    caption = build_movie_caption(movie)
    image_url = movie.get("#IMG_POSTER", FALLBACK_POSTER)
    markup = build_pagination_keyboard(page=page, total_results=len(results), query=query)
    
    # Edit the existing photo and caption with the new page's data
    await callback_query.edit_message_media(
        media=InputMediaPhoto(media=image_url, caption=caption),
        reply_markup=markup
    )
