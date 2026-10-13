// Getting Elements from the html

const typingForm = document.querySelector(".typing-form");
const chat = document.querySelector(".chat-list");
const suggestions = document.querySelectorAll(".suggestion");
const toggleTheme = document.querySelector("#theme-toogle-button");
const deleteChat = document.querySelector("#delete-chat-button");

//Default state for api handling.
let userMessage = null;
let apiResponse = false;

//API Configuration

const API_URL = "/chat";

// saving the theme in the local storage

const chatStorageKey = () => {
  try {
    const token = localStorage.getItem('accessToken');
    const subject = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))).sub;
    return /^\d+$/.test(subject) ? `savedchats-v2:${subject}` : null;
  } catch (_) { return null; }
};
const saveChats = () => {
  const key = chatStorageKey();
  if (!key) return;
  const messages = Array.from(chat.querySelectorAll('.message')).map(element => ({
    role: element.classList.contains('outgoing') ? 'outgoing' : 'incoming',
    text: element.querySelector('.text')?.textContent || ''
  })).slice(-100);
  localStorage.setItem(key, JSON.stringify(messages));
};
const loadData = () => {
  const isLightMode = localStorage.getItem('themeColor') === 'light_mode';
  document.body.classList.toggle('light_mode', isLightMode);
  toggleTheme.innerText = isLightMode ? 'dark_mode' : 'light_mode';
  chat.replaceChildren();
  // The old HTML storage format is unsafe and is intentionally not restored.
  localStorage.removeItem('savedchats');
  let messages = [];
  try { messages = JSON.parse(localStorage.getItem(chatStorageKey()) || '[]'); } catch (_) {}
  if (Array.isArray(messages)) {
    for (const item of messages.slice(-100)) {
      if (!item || !['incoming', 'outgoing'].includes(item.role) || typeof item.text !== 'string') continue;
      const element = createMessage('<div class="message-content"><p class="text"></p></div>', item.role);
      element.querySelector('.text').textContent = item.text.slice(0, 20000);
      chat.appendChild(element);
    }
  }
  document.body.classList.toggle('hide-header', chat.children.length > 0);
  chat.scrollTo(0, chat.scrollHeight);
};

//darkmode lightmode toggle theme

toggleTheme.addEventListener("click", () => {
  const isLightMode = document.body.classList.toggle("light_mode");
  localStorage.setItem("themeColor", isLightMode ? "light_mode" : "dark_mode");
  toggleTheme.innerText = isLightMode ? "dark_mode" : "light_mode";
});

//creating a div element for messages

const createMessage = (content, ...classes) => {
  const div = document.createElement("div");
  div.classList.add("message", ...classes);
  div.innerHTML = content;
  return div;
};

//creating the typing effect for displaying words one by one

const typingEffect = (text, textElement, messageDiv) => {
  const words = text.split(" ");
  let currentWordIndex = 0;

  //append the words one by one with space

  const typingInterval = setInterval(() => {
    textElement.innerText +=
      (currentWordIndex === 0 ? "" : " ") + words[currentWordIndex++];
    messageDiv.querySelector(".icon").classList.add("hide");

    //if all the words are displayed
    if (currentWordIndex === words.length) {
      clearInterval(typingInterval);
      apiResponse = false;
      messageDiv.querySelector(".icon").classList.remove("hide");
      saveChats();
    }
    chat.scrollTo(0, chat.scrollHeight); // scroll to bottom
  }, 100);
};

// Fetching the data from the api based on the user prompt

const generateResponse = async (messageDiv) => {
  //Getting the text element and sending it to api

  const textElement = messageDiv.querySelector(".text");

  try {
    const response = await apiFetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({message: userMessage}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Chat request failed.");

    // Get the response text and removing the unnesscary spaces,asteriks frokm the api
    const apiData = data.text;

    // display the data with typing effect after getting response from the api
    typingEffect(apiData, textElement, messageDiv);
  } catch (error) {
    apiResponse = false;
    textElement.innerText = error.message;
    textElement.parentElement.closest(".message").classList.add("error");
  } finally {
    messageDiv.classList.remove("loading");
  }
};

// Creating a loading animation while waiting for the response from the api
const loadingAnimation = () => {
  const tag = `<div class="message-content">
                     <img class="avatar" src="./images/svg.svg" alt="Gemini logo">
                     <p class="text"></p>
                     <div class="loading-indicator">
                     <div class="loading-bar"></div>
                     <div class="loading-bar"></div>
                     <div class="loading-bar"></div>
                     </div>
                     </div>
                     <span onClick="copyMessage(this)" class="icon material-symbols-rounded">content_copy</span>`;

  const messageDiv = createMessage(tag, "incoming", "loading");
  chat.appendChild(messageDiv);
  chat.scrollTo(0, chat.scrollHeight); // scroll to bottom
  generateResponse(messageDiv);
};

//copy the responses
const copyMessage = (copyButton) => {
  const messageText = copyButton.parentElement.querySelector(".text").innerText;
  navigator.clipboard.writeText(messageText);
  copyButton.innerText = "done";
  setTimeout(() => (copyButton.innerText = "content_copy"), 1000);
};

// Handling the message from the prompt to API and adding loading effect when the response came.

const sendMessage = () => {
  userMessage =
    typingForm.querySelector(".typing-input").value.trim() || userMessage;
  // Exit if there is no message or response is generating
  if (!userMessage || apiResponse) return;
  apiResponse = true;
  const tag = `<div class="message-content">
                     <img class="avatar" src="images/er.svg" alt="user profile photo">
                     <p class="text"></p>
                     </div>`;
  const sendMessageDiv = createMessage(tag, "outgoing");
  sendMessageDiv.querySelector(".text").innerText = userMessage;
  chat.appendChild(sendMessageDiv);

  //to clear the prompt values
  typingForm.reset();
  document.body.classList.add("hide-header");
  chat.scrollTo(0, chat.scrollHeight); // scroll to bottom
  setTimeout(loadingAnimation, 500);
};

// Genearting the api response while clicking the suggestions
suggestions.forEach((suggestion) => {
    suggestion.addEventListener("click", () => {
    userMessage = suggestion.querySelector(".text").innerText;
    sendMessage();
  });
});

// Delete button to delete all the chats

deleteChat.addEventListener("click", () => {
  if (confirm("Are you sure you want to delete all the chats")) {
    const key = chatStorageKey();
    if (key) localStorage.removeItem(key);
    loadData();
  }
});

typingForm.addEventListener("submit", (e) => {
  e.preventDefault();
  sendMessage();
});

loadData();
