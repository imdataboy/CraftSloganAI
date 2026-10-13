document.querySelector('form').addEventListener('submit', function (event) {
    event.preventDefault(); // Prevent page refresh

    // Get user inputs
    const emailOrUsername = document.querySelector('input[placeholder="Email or Username"]').value;
    const password = document.querySelector('input[placeholder="Password"]').value;


    fetch(new URL('/login', window.API_BASE), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            email_or_username: emailOrUsername,
            password: password,
        }),
    })
        .then(response => {
            console.log('Response status:', response.status);
            return response.json();
        })
        .then(data => {
            // Create a message box
            const messageBox = document.createElement('div');
            messageBox.id = 'notification-box';
            messageBox.style.position = 'fixed';
            messageBox.style.bottom = '20px';
            messageBox.style.right = '20px';
            messageBox.style.padding = '15px 30px';
            messageBox.style.color = '#fff';
            messageBox.style.fontSize = '16px';
            messageBox.style.fontWeight = 'bold';
            messageBox.style.zIndex = '1000';
            messageBox.style.backgroundColor = data.error ? '#e74c3c' : '#2ecc71'; // Red for error, green for success
            messageBox.style.borderRadius = '8px';
            messageBox.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.2)';
            messageBox.style.opacity = '1';
            messageBox.style.transition = 'opacity 0.5s ease';

            messageBox.textContent = data.error ? `Error: ${data.error}` : `Welcome back, ${data.message}!`;

            document.body.appendChild(messageBox);

            // Store access token if login is successful
            if (!data.error) {
                localStorage.setItem('accessToken', data.access_token); // Save token
            }

            // Message box timeout
            setTimeout(() => {
                messageBox.style.opacity = '0'; // Fade out
                setTimeout(() => {
                    messageBox.remove(); // Remove from DOM
                    if (!data.error) {
                        window.location.href = 'menuPage.html'; // Redirect to the dashboard
                    }
                }, 500);
            }, 4000);
        })
        .catch(error => {
            console.error('Fetch Error:', error);

            // Show error message
            const errorBox = document.createElement('div');
            errorBox.id = 'error-box';
            errorBox.style.position = 'fixed';
            errorBox.style.bottom = '20px';
            errorBox.style.right = '20px';
            errorBox.style.padding = '15px 30px';
            errorBox.style.color = '#fff';
            errorBox.style.fontSize = '16px';
            errorBox.style.fontWeight = 'bold';
            errorBox.style.zIndex = '1000';
            errorBox.style.backgroundColor = '#e74c3c'; // Red for error
            errorBox.style.borderRadius = '8px';
            errorBox.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.2)';
            errorBox.style.opacity = '1';
            errorBox.style.transition = 'opacity 0.5s ease';
            errorBox.textContent = 'Login failed. Please try again.';

            document.body.appendChild(errorBox);

            // Remove error message after 4 seconds
            setTimeout(() => {
                errorBox.style.opacity = '0'; // Fade out
                setTimeout(() => errorBox.remove(), 500);
            }, 4000);
        });
});
