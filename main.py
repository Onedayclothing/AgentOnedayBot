        function openTelegram() {
            if (Object.keys(cart).length === 0) {
                alert(translations[currentLang].empty_cart);
                return;
            }

            let nameInput = document.getElementById('custName');
            let phoneInput = document.getElementById('custPhone');
            let addressInput = document.getElementById('custAddress');
            let mapUrlInput = document.getElementById('custMapUrl');

            let name = nameInput.value.trim();
            let phone = phoneInput.value.trim();
            let address = addressInput.value.trim();
            let mapUrl = mapUrlInput ? mapUrlInput.value.trim() : '';

            let hasError = false;
            if (!name) { nameInput.classList.add('error'); hasError = true; }
            if (!phone) { phoneInput.classList.add('error'); hasError = true; }
            if (!address) { addressInput.classList.add('error'); hasError = true; }

            if (hasError) {
                alert(translations[currentLang].alert_fill);
                return;
            }

            let cleanPhone = phone.replace(/[^0-9]/g, '');
            if (cleanPhone.length < 8) {
                phoneInput.classList.add('error');
                alert(translations[currentLang].alert_phone_invalid);
                return;
            }

            saveUserInfo();

            let message = "🛍️ Oneday Clothing — Order\n\n";
            message += "👤 ព័ត៌មានអតិថិជន\n";
            message += `• ឈ្មោះ: ${name}\n`;
            message += `• លេខទូរស័ព្ទ: ${phone}\n`;
            message += `• អាសយដ្ឋាន: ${address}\n`;
            if (mapUrl) {
                let cleanCoords = mapUrl.replace(/\s+/g, '');
                message += `• ទីតាំង Map: ${mapUrl}\n`;
                message += `• Link Google Maps: https://www.google.com/maps?q=${cleanCoords}\n`;
            }
            message += "\n📦 ទំនិញ\n";

            let index = 1;
            let subtotalPrice = 0;

            const sizeOrder = { 'S': 1, 'M': 2, 'L': 3, 'XL': 4, 'XXL': 5 };
            let sortedKeys = Object.keys(cart).sort((a, b) => {
                let itemA = cart[a], itemB = cart[b];
                let refA = parseInt(itemA.ref.replace(/\D/g, '')) || 0;
                let refB = parseInt(itemB.ref.replace(/\D/g, '')) || 0;
                if (refA !== refB) return refA - refB;
                return (sizeOrder[itemA.size] || 99) - (sizeOrder[itemB.size] || 99);
            });

            for (let key of sortedKeys) {
                let item = cart[key];
                let itemTotal = item.price * item.qty;
                subtotalPrice += itemTotal;
                let localizedTitle = translations[currentLang][item.titleKey] || item.titleKey;
                let refPart = item.ref ? `[${item.ref}] ` : '';
                message += `${index}. ${refPart}${localizedTitle}\n`;
                message += `    Size: ${item.size} × ${item.qty} — $${itemTotal.toFixed(2)}\n`;
                index++;
            }

            let grandTotal = subtotalPrice + deliveryFee;

            message += `\n💰 សរុប\n`;
            message += `• តម្លៃទំនិញ: $${subtotalPrice.toFixed(2)}\n`;
            message += `• ថ្លៃដឹកជញ្ជូន: $${deliveryFee.toFixed(2)}\n`;
            message += `• សរុបទាំងអស់: $${grandTotal.toFixed(2)}`;

            let targetUrl = `https://t.me/${TELEGRAM_USERNAME}?text=${encodeURIComponent(message)}`;

            // បើកតាម Telegram Native Link (គ្មាន Warning, ដើរគ្រប់ Mini App)
            if (tg && tg.openTelegramLink) {
                tg.openTelegramLink(targetUrl);
            } else {
                window.location.href = targetUrl;
            }
        }
