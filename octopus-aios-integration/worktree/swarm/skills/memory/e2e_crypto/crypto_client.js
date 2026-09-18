/**
 * Octopus E2E Crypto Client — шифрование на стороне клиента
 * Использует WebCrypto API (AES-256-GCM + PBKDF2)
 */
class OctopusCrypto {
    constructor() {
        this.algorithm = 'AES-GCM';
        this.keyLength = 256;
        this.iterations = 100000;
    }

    // Генерация случайной соли
    generateSalt(length = 16) {
        return crypto.getRandomValues(new Uint8Array(length));
    }

    // Генерация случайного IV
    generateIV(length = 12) {
        return crypto.getRandomValues(new Uint8Array(length));
    }

    // Получение ключа из пароля (PBKDF2)
    async deriveKey(password, salt) {
        const encoder = new TextEncoder();
        const keyMaterial = await crypto.subtle.importKey(
            'raw',
            encoder.encode(password),
            'PBKDF2',
            false,
            ['deriveKey']
        );

        return crypto.subtle.deriveKey(
            {
                name: 'PBKDF2',
                salt: salt,
                iterations: this.iterations,
                hash: 'SHA-256'
            },
            keyMaterial,
            { name: this.algorithm, length: this.keyLength },
            true,
            ['encrypt', 'decrypt']
        );
    }

    // Шифрование данных
    async encrypt(data, password) {
        const encoder = new TextEncoder();
        const salt = this.generateSalt();
        const iv = this.generateIV();
        const key = await this.deriveKey(password, salt);

        const encrypted = await crypto.subtle.encrypt(
            { name: this.algorithm, iv: iv },
            key,
            encoder.encode(JSON.stringify(data))
        );

        // Объединяем: salt + iv + encrypted
        const result = new Uint8Array(salt.length + iv.length + encrypted.byteLength);
        result.set(salt, 0);
        result.set(iv, salt.length);
        result.set(new Uint8Array(encrypted), salt.length + iv.length);

        return this._arrayBufferToBase64(result.buffer);
    }

    // Расшифровка данных
    async decrypt(encryptedData, password) {
        const data = this._base64ToArrayBuffer(encryptedData);
        const salt = data.slice(0, 16);
        const iv = data.slice(16, 28);
        const ciphertext = data.slice(28);

        const key = await this.deriveKey(password, salt);

        const decrypted = await crypto.subtle.decrypt(
            { name: this.algorithm, iv: iv },
            key,
            ciphertext
        );

        const decoder = new TextDecoder();
        return JSON.parse(decoder.decode(decrypted));
    }

    // Хэширование пароля для проверки
    async hashPassword(password) {
        const encoder = new TextEncoder();
        const data = encoder.encode(password);
        const hash = await crypto.subtle.digest('SHA-256', data);
        return this._arrayBufferToBase64(hash);
    }

    // Вспомогательные функции
    _arrayBufferToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.length; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return btoa(binary);
    }

    _base64ToArrayBuffer(base64) {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes;
    }
}

// Экспорт для WebDAV прокси
if (typeof module !== 'undefined' && module.exports) {
    module.exports = OctopusCrypto;
}

// Глобальный экспорт
if (typeof window !== 'undefined') {
    window.OctopusCrypto = OctopusCrypto;
}
