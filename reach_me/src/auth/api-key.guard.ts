import { timingSafeEqual } from 'node:crypto';
import {
  CanActivate,
  ExecutionContext,
  Injectable,
  UnauthorizedException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Reflector } from '@nestjs/core';
import type { Request } from 'express';
import { IS_PUBLIC_KEY } from './public.decorator';

@Injectable()
export class ApiKeyGuard implements CanActivate {
  constructor(
    private readonly configService: ConfigService,
    private readonly reflector: Reflector,
  ) {}

  canActivate(context: ExecutionContext): boolean {
    const isPublic = this.reflector.getAllAndOverride<boolean>(IS_PUBLIC_KEY, [
      context.getHandler(),
      context.getClass(),
    ]);
    if (isPublic) {
      return true;
    }

    const configuredKey = this.configService.get<string>('API_KEY');
    if (!configuredKey) {
      return true;
    }

    const request = context.switchToHttp().getRequest<Request>();
    const providedKey = this.extractKey(request);

    if (!providedKey || !this.safeCompare(providedKey, configuredKey)) {
      throw new UnauthorizedException('Invalid API key');
    }

    return true;
  }

  private safeCompare(a: string, b: string): boolean {
    const bufA = Buffer.from(a, 'utf8');
    const bufB = Buffer.from(b, 'utf8');

    if (bufA.length !== bufB.length) {
      // Compare against self to maintain constant time
      timingSafeEqual(bufA, bufA);
      return false;
    }

    return timingSafeEqual(bufA, bufB);
  }

  private extractKey(request: Request): string | null {
    const header = request.headers['x-api-key'] ?? request.headers.authorization;
    if (!header) {
      return null;
    }

    if (Array.isArray(header)) {
      return this.normalizeKey(header[0]);
    }

    return this.normalizeKey(header);
  }

  private normalizeKey(value: string): string | null {
    const trimmed = value.trim();
    if (!trimmed) {
      return null;
    }

    if (trimmed.toLowerCase().startsWith('bearer ')) {
      const token = trimmed.slice('bearer '.length).trim();
      return token || null;
    }

    return trimmed;
  }
}
