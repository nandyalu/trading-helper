import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { ActionResult, TransactionRequest } from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class TransactionsService {
  private readonly http = inject(HttpClient);

  buy(payload: TransactionRequest): Promise<ActionResult> {
    return firstValueFrom(this.http.post<ActionResult>('/api/transactions/buy', payload));
  }

  sell(payload: TransactionRequest): Promise<ActionResult> {
    return firstValueFrom(this.http.post<ActionResult>('/api/transactions/sell', payload));
  }
}
