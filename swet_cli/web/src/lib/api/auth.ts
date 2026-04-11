import { api } from './client';
import type {
	RegisterRequest,
	OTPSendRequest,
	OTPVerifyRequest,
	TokenResponse,
	MessageResponse
} from './types';

export async function register(data: RegisterRequest): Promise<MessageResponse> {
	return api.post('auth/register', { json: data }).json<MessageResponse>();
}

export async function sendOtp(data: OTPSendRequest): Promise<MessageResponse> {
	return api.post('auth/otp/send', { json: data }).json<MessageResponse>();
}

export async function verifyOtp(data: OTPVerifyRequest): Promise<TokenResponse> {
	return api.post('auth/otp/verify', { json: data }).json<TokenResponse>();
}
