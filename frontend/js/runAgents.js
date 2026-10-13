const API_URL_GENERATE_POST = "/run_agents_manual";
const API_URL_RUN_AGENTS_EMAIL = "/run_agents";

async function generatePostManually() {
  const inputField = document.querySelector("#generate-email input");
  const loadingSymbol = document.getElementById("loading-symbol-manual");
  const prompt = inputField.value.trim();

  if (!prompt) {
    alert("Please enter a valid product description.");
    return;
  }

  try {
    // Show loading symbol
    loadingSymbol.style.display = "block";

    // Send the request to the backend
    const response = await apiFetch(API_URL_GENERATE_POST, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        subject: "Manual Post",
        body: prompt, // Correctly send the trimmed input
        sender: "manual_user",
      }),
    });

    const result = await response.json();

    if (response.ok) {
      alert("Post generated successfully!");

    } else {
      console.error("Failed to generate post:", result.error);
      throw new Error(result.error || "Could not generate the post.");
    }
  } catch (error) {
    console.error("Error during post generation:", error.stack || error);
    alert(error.message || "Post generation failed.");
  } finally {
    // Hide loading symbol
    loadingSymbol.style.display = "none";
  }
}

async function runAgents() {
  const loadingSymbol = document.getElementById("loading-symbol-email");

  try {
    // Show loading symbol
    loadingSymbol.style.display = "block";

    // Send a POST request to trigger the agents
    const response = await apiFetch(API_URL_RUN_AGENTS_EMAIL, {
      method: "POST",
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.error || "Failed to run agents.");
    }

    const result = await response.json();

    // Handle success response
    alert("Agents executed successfully!");
    console.log("Response:", result.message); // Log the success message
  } catch (error) {
    // Handle errors more gracefully
    console.error("Error running agents:", error.message);
    alert(`Error: ${error.message}`);
  } finally {
    // Hide loading symbol
    loadingSymbol.style.display = "none";
  }
}


// Attach event listener to the "Generate Post" button
document
  .querySelector("#run-agents-button")
  .addEventListener("click", runAgents);

// Attach event listener to the "Generate Post" button
document
  .querySelector("#generate-email button")
  .addEventListener("click", generatePostManually);
