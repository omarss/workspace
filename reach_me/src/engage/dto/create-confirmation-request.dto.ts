import {
  IsEnum,
  IsInt,
  IsNotEmpty,
  IsOptional,
  IsString,
  IsUrl,
  Matches,
  Max,
  MaxLength,
  Min,
} from 'class-validator';
import { Channel, Language } from '../types';

export class CreateConfirmationRequestDto {
  @IsString()
  @IsNotEmpty()
  @Matches(/^\+[1-9]\d{6,14}$/, {
    message: 'mobileNumber must be in E.164 format (example: +201234567890)',
  })
  mobileNumber!: string;

  @IsString()
  @IsNotEmpty()
  @MaxLength(1000)
  message!: string;

  @IsEnum(Language)
  language!: Language;

  @IsEnum(Channel)
  channel!: Channel;

  @IsOptional()
  @IsUrl()
  callbackUrl?: string;

  @IsOptional()
  @IsInt()
  @Min(60)
  @Max(86400)
  ttlSeconds?: number;
}
