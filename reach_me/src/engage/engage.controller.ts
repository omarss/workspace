import { Body, Controller, Get, Param, Post } from '@nestjs/common';
import { CreateConfirmationRequestDto } from './dto/create-confirmation-request.dto';
import { SetResultDto } from './dto/set-result.dto';
import { EngageService } from './engage.service';
import { EngageQueueService } from './queue/engage-queue.service';
import type { ConfirmationRequest } from './types';

@Controller('v1/engage')
export class EngageController {
  constructor(
    private readonly engageService: EngageService,
    private readonly queueService: EngageQueueService,
  ) {}

  @Post()
  async create(
    @Body() dto: CreateConfirmationRequestDto,
  ): Promise<{ requestId: string; result: ConfirmationRequest['result'] }> {
    const created = await this.engageService.create(dto);
    void this.queueService.enqueue(created);
    return { requestId: created.id, result: created.result };
  }

  @Get(':requestId')
  get(@Param('requestId') requestId: string): Promise<ConfirmationRequest> {
    return this.engageService.get(requestId);
  }

  @Post(':requestId/result')
  setResult(
    @Param('requestId') requestId: string,
    @Body() dto: SetResultDto,
  ): Promise<ConfirmationRequest> {
    return this.engageService.setResult(requestId, dto.result);
  }
}
