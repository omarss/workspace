import { IsEnum } from 'class-validator';
import { ConfirmationResult } from '../types';

export class SetResultDto {
  @IsEnum(ConfirmationResult)
  result!: ConfirmationResult;
}
