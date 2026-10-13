// API Endpoint URLs
const API_URL_VALIDATE_POST = "/validate_post";
const API_URL_DELETE_POST = "/delete_scheduled_post";

// Global variable to track the current post ID being scheduled
let currentPostId = null;

// Function to Fetch Draft Posts from Backend
async function fetchDraftPosts() { 
  try {
    console.log("Fetching draft posts...");
    const response = await apiFetch(API_URL_VALIDATE_POST, { method: "GET" });
    if (!response.ok) throw new Error("Failed to fetch draft posts");

    const posts = await response.json();

    // Populate Draft Posts in UI
    const postsContainer = document.querySelector(".content-wrapper");
    postsContainer.innerHTML = '<h3 class="text-center mb-4" style="color: #fe3f40;">Draft Posts</h3>';

    if (posts.length === 0) {
      postsContainer.innerHTML += "<p>No draft posts found.</p>";
      return;
    }

    posts.forEach(post => {
      const postCard = document.createElement("div");
      postCard.className = "post-card";

      // Use the dynamic image path from the backend
      
      // Use the slogan if available, otherwise fallback to subject or default text
      const title = post.post_text || post.email_subject || "Untitled Post";

      const img = document.createElement('img');
      img.className = 'post-image';
      img.alt = 'Draft image';
      loadPrivateImage(img, post.image_path);
      const details = document.createElement('div');
      details.className = 'post-details';
      const heading = document.createElement('h5');
      heading.textContent = title;
      const created = document.createElement('p');
      created.textContent = `Created at: ${post.created_at || 'No date'}`;
      details.append(heading, created);
      const actions = document.createElement('div');
      actions.className = 'post-actions';
      for (const [label, icon, action] of [
        ['Reject', 'fa-times-circle', () => rejectPost(post.id)],
        ['Schedule', 'fa-calendar-alt', () => openScheduleModal(post.id)],
        ['Post Now', 'fa-paper-plane', () => approvePost(post.id)]
      ]) {
        const button = document.createElement('button');
        button.title = label;
        const symbol = document.createElement('i');
        symbol.className = `fas ${icon}`;
        button.appendChild(symbol);
        button.addEventListener('click', action);
        actions.appendChild(button);
      }
      postCard.append(img, details, actions);
      postsContainer.appendChild(postCard);
    });
  } catch (error) {
    console.error("Error fetching draft posts:", error);
    alert("Failed to load draft posts. Check the console for details.");
  }
}


// Function to Open the Schedule Modal
function openScheduleModal(postId) {
  currentPostId = postId;
  const modal = document.getElementById("scheduleModal");
  const backdrop = document.getElementById("modalBackdrop");

  modal.style.display = "block";
  backdrop.style.display = "block";
}

// Function to Close the Modal
function closeModal() {
  const modal = document.getElementById("scheduleModal");
  const backdrop = document.getElementById("modalBackdrop");

  modal.style.display = "none";
  backdrop.style.display = "none";
  currentPostId = null;
}

async function confirmSchedule() {
  const selectedDate = new Date(document.getElementById("scheduleDateTime").value);

  if (!Number.isFinite(selectedDate.getTime())) {
    alert("Please select a valid date and time.");
    return;
  }

  const scheduleDateTime = selectedDate.toISOString();

  // Log the data being sent
  console.log("Payload being sent:", {
    post_id: currentPostId,
    action: "approve",
    schedule_time: scheduleDateTime,
  });

  try {
    const response = await apiFetch(API_URL_VALIDATE_POST, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        post_id: currentPostId,
        action: "approve",
        schedule_time: scheduleDateTime,
      }),
    });

    const result = await response.json();
    console.log("Response from server:", result);

    if (response.ok) {
      alert(result.message);
      closeModal();
      fetchDraftPosts(); // Refresh Posts
    } else {
      alert(result.error);
    }
  } catch (error) {
    console.error("Error scheduling post:", error);
    alert("Failed to schedule post. Check the console for details.");
  }
}


// Function to Delete a Scheduled Post
async function deletePost(postId) {
  try {
    const response = await apiFetch(API_URL_DELETE_POST, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ post_id: postId }),
    });
    const result = await response.json();

    if (response.ok) {
      alert(result.message);
      fetchDraftPosts(); // Refresh Posts
    } else {
      alert(result.error);
    }
  } catch (error) {
    console.error("Error deleting post:", error);
    alert(error.message || "Post deletion failed.");
  }
}

async function rejectPost(postId) {
  try {
    const response = await apiFetch(API_URL_VALIDATE_POST, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        post_id: postId,
        action: "reject", // Marks the post as rejected
      }),
    });

    const result = await response.json();
    if (response.ok) {
      alert(result.message || "Post rejected successfully!");
      fetchDraftPosts(); // Refresh posts
    } else {
      alert(result.error || "Failed to reject the post.");
    }
  } catch (error) {
    console.error("Error rejecting post:", error);
    alert("An error occurred while rejecting the post. Check the console for details.");
  }
}

async function approvePost(postId) {
  try {
    const response = await apiFetch(API_URL_VALIDATE_POST, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        post_id: postId,
        action: "approve", // Marks the post as approved
      }),
    });

    const result = await response.json();
    if (response.ok) {
      alert(result.message || "Post approved successfully!");
      fetchDraftPosts(); // Refresh posts
    } else {
      alert(result.error || "Failed to approve the post.");
    }
  } catch (error) {
    console.error("Error approving post:", error);
    alert("An error occurred while approving the post. Check the console for details.");
  }
}


// Load Draft Posts on Page Load
document.addEventListener("DOMContentLoaded", fetchDraftPosts);
