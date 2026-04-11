<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import { app } from '$lib/stores/app.svelte';
	import * as authApi from '$lib/api/auth';
	import { TelInput, countries } from 'svelte-tel-input';
	import type { CountryCode } from 'svelte-tel-input/types';

	type Step = 'identify' | 'otp';
	type Mode = 'email' | 'phone';

	let step = $state<Step>('identify');
	let mode = $state<Mode>('phone');
	let email = $state('');
	let otpDigits = $state(['', '', '', '', '', '']);
	let loading = $state(false);
	let error = $state('');

	// Phone input state
	let phoneCountry = $state<CountryCode | null>('SA');
	let phoneValue = $state('');
	let phoneValid = $state(false);

	// Refs for OTP digit inputs
	let otpInputs: HTMLInputElement[] = [];

	// What was sent the OTP (for display)
	let sentTo = $derived(mode === 'email' ? email : phoneValue);

	function payload(): { email?: string; mobile?: string } {
		if (mode === 'email') return { email };
		return { mobile: phoneValue };
	}

	function canSubmit(): boolean {
		if (mode === 'email') return email.trim().length > 0;
		return phoneValid && phoneValue.length > 0;
	}

	async function handleIdentify() {
		if (!canSubmit()) return;
		error = '';
		loading = true;

		try {
			await authApi.sendOtp(payload());
			step = 'otp';
			setTimeout(() => otpInputs[0]?.focus(), 50);
		} catch (e: unknown) {
			const msg = e instanceof Error ? e.message : 'Something went wrong';
			try {
				const body = await (e as { response?: Response }).response?.json();
				error = body?.detail ?? body?.message ?? msg;
			} catch {
				error = msg;
			}
		} finally {
			loading = false;
		}
	}

	function handleOtpInput(index: number, event: Event) {
		const input = event.target as HTMLInputElement;
		const value = input.value.replace(/\D/g, '');

		if (value.length > 1) {
			const digits = value.slice(0, 6).split('');
			for (let i = 0; i < digits.length && index + i < 6; i++) {
				otpDigits[index + i] = digits[i];
			}
			const nextIndex = Math.min(index + digits.length, 5);
			otpInputs[nextIndex]?.focus();
		} else {
			otpDigits[index] = value;
			if (value && index < 5) {
				otpInputs[index + 1]?.focus();
			}
		}

		if (otpDigits.every((d) => d !== '')) {
			handleVerify();
		}
	}

	function handleOtpKeydown(index: number, event: KeyboardEvent) {
		if (event.key === 'Backspace' && !otpDigits[index] && index > 0) {
			otpInputs[index - 1]?.focus();
		}
	}

	async function handleVerify() {
		const code = otpDigits.join('');
		if (code.length !== 6) return;

		error = '';
		loading = true;

		try {
			const tokens = await authApi.verifyOtp({
				...payload(),
				code
			});
			auth.setTokens(tokens.access_token, tokens.refresh_token);
			app.toast('Logged in', 'success');
			goto('/today');
		} catch (e: unknown) {
			try {
				const body = await (e as { response?: Response }).response?.json();
				error = body?.detail ?? 'Invalid code';
			} catch {
				error = 'Verification failed';
			}
			otpDigits = ['', '', '', '', '', ''];
			otpInputs[0]?.focus();
		} finally {
			loading = false;
		}
	}
</script>

<div class="dot-grid flex min-h-dvh items-center justify-center px-4">
	<div class="fade-in w-full max-w-sm">
		<!-- Logo / Title -->
		<div class="mb-8 text-center">
			<h1 class="font-mono text-3xl font-bold tracking-tight text-accent">swet</h1>
			<p class="mt-2 text-sm text-text-muted">Train engineering judgment, not trivia</p>
			<p class="mt-1 text-xs text-text-dim">Adaptive practice for debugging, architecture, code review, and system design</p>
		</div>

		<!-- Card -->
		<div class="rounded-xl border border-border bg-bg-subtle p-6">
			{#if step === 'identify'}
				<!-- Mode toggle: Phone / Email -->
				<div class="mb-5 flex rounded-lg border border-border bg-bg-muted p-1">
					<button
						class="flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors
							{mode === 'phone' ? 'bg-bg-elevated text-text' : 'text-text-muted hover:text-text'}"
						onclick={() => (mode = 'phone')}
					>
						Phone
					</button>
					<button
						class="flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors
							{mode === 'email' ? 'bg-bg-elevated text-text' : 'text-text-muted hover:text-text'}"
						onclick={() => (mode = 'email')}
					>
						Email
					</button>
				</div>

				<form onsubmit={(e) => { e.preventDefault(); handleIdentify(); }}>
					{#if mode === 'phone'}
						<label class="mb-1 block text-xs font-medium text-text-muted" for="phone-input">
							Phone number
						</label>
						<div class="flex gap-2">
							<select
								bind:value={phoneCountry}
								class="w-24 shrink-0 rounded-lg border border-border bg-bg-muted px-2 py-2.5
									text-xs text-text focus:border-accent focus:outline-none"
								disabled={loading}
							>
								{#each countries as c (c.id)}
									<option value={c.iso2}>
										{c.iso2} +{c.dialCode}
									</option>
								{/each}
							</select>
							<TelInput
								id="phone-input"
								bind:country={phoneCountry}
								bind:value={phoneValue}
								bind:valid={phoneValid}
								options={{ autoPlaceholder: false }}
								class="w-full rounded-lg border border-border bg-bg-muted px-3 py-2.5 text-sm
									text-text placeholder:text-text-dim focus:border-accent focus:outline-none"
								disabled={loading}
								placeholder="5XX XXX XXXX"
							/>
						</div>
					{:else}
						<label class="mb-1 block text-xs font-medium text-text-muted" for="email-input">
							Email address
						</label>
						<input
							id="email-input"
							type="email"
							bind:value={email}
							placeholder="you@example.com"
							class="w-full rounded-lg border border-border bg-bg-muted px-3 py-2.5 text-sm
								text-text placeholder:text-text-dim focus:border-accent focus:outline-none"
							disabled={loading}
						/>
					{/if}

					{#if error}
						<p class="mt-2 text-xs text-error">{error}</p>
					{/if}

					<button
						type="submit"
						disabled={loading || !canSubmit()}
						class="mt-4 w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-bg
							transition-colors hover:bg-accent/90 disabled:opacity-50"
					>
						{#if loading}
							<span class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-bg border-t-transparent"></span>
						{:else}
							Continue
						{/if}
					</button>
				</form>

			{:else}
				<!-- OTP verification -->
				<div class="text-center">
					<p class="mb-1 text-sm text-text">Enter verification code</p>
					<p class="mb-6 text-xs text-text-muted">
						Sent to <span class="font-mono text-accent">{sentTo}</span>
					</p>
				</div>

				<div class="flex justify-center gap-2">
					{#each otpDigits as digit, i}
						<input
							bind:this={otpInputs[i]}
							type="text"
							inputmode="numeric"
							maxlength="6"
							value={digit}
							oninput={(e) => handleOtpInput(i, e)}
							onkeydown={(e) => handleOtpKeydown(i, e)}
							class="h-12 w-10 rounded-lg border border-border bg-bg-muted text-center
								font-mono text-lg text-text focus:border-accent focus:outline-none"
							disabled={loading}
						/>
					{/each}
				</div>

				{#if error}
					<p class="mt-3 text-center text-xs text-error">{error}</p>
				{/if}

				{#if loading}
					<div class="mt-4 flex justify-center">
						<span class="inline-block h-5 w-5 animate-spin rounded-full border-2 border-accent border-t-transparent"></span>
					</div>
				{/if}

				<button
					class="mt-6 w-full text-center text-xs text-text-muted hover:text-accent"
					onclick={() => { step = 'identify'; error = ''; otpDigits = ['', '', '', '', '', '']; }}
				>
					Use a different {mode === 'phone' ? 'number' : 'email'}
				</button>
			{/if}
		</div>

		<p class="mt-4 text-center text-xs text-text-dim">
			30-second sign in. No passwords.
		</p>
	</div>
</div>
